"""Assessment-scoped QR intake. QR identifies paper groups, never students."""

import re
import uuid
from collections import Counter
from datetime import datetime

import cv2
import numpy as np
import pymupdf
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from rest_framework.exceptions import ValidationError

from submissions.models import ScriptPage, ScriptUpload, Submission, SubmissionAudit


def label_order(label):
    if not isinstance(label, str) or not re.fullmatch(r"P[1-9][0-9]{0,3}", label):
        raise ValueError("Invalid page label")
    return int(label[1:])


def parse_qr(value):
    if not isinstance(value, str):
        raise ValueError("QR value must be a string.")
    values = [part.strip() for part in value.split(",")]
    if len(values) != 5 or any(len(part) > 80 for part in values):
        raise ValueError("QR must have five bounded fields")
    module, date, test, label, number = values
    if not re.fullmatch(r"[A-Za-z0-9_-]+", module) or not re.fullmatch(
        r"[A-Za-z0-9_-]+", test
    ):
        raise ValueError("Invalid module or test")
    if not re.fullmatch(r"\d{8}", date):
        raise ValueError("Invalid date")
    datetime.strptime(date, "%Y%m%d")
    label_order(label)
    if not re.fullmatch(r"#[1-9][0-9]{0,8}", number):
        raise ValueError("Invalid test number")
    return dict(
        module=module, date=date, test=test, page_label=label, test_number=number
    )


def decode_page(image):
    detector = cv2.QRCodeDetector()
    values = set()
    crops = [image, cv2.resize(image, None, fx=0.5, fy=0.5)]
    height, width = image.shape[:2]
    # Small printed codes may be detected but not decoded on a full A4/A3
    # scan. Overlapping tiles retain quiet zones without assuming QR position.
    for row in range(4):
        for column in range(4):
            y1, y2 = max(0, row * height // 4 - 48), min(
                height, (row + 1) * height // 4 + 48
            )
            x1, x2 = max(0, column * width // 4 - 48), min(
                width, (column + 1) * width // 4 + 48
            )
            crops.append(image[y1:y2, x1:x2])
    for crop in crops:
        try:
            found, decoded, _, _ = detector.detectAndDecodeMulti(crop)
            if found:
                values.update(value for value in decoded if value)
            single, points, _ = detector.detectAndDecode(crop)
            if single:
                values.add(single)
            elif points is not None:
                # OpenCV's sampling of tiny vector QR edges is scale-sensitive.
                # Retry detected candidates at nearby scales, retaining all
                # payloads so conflicting codes still require review.
                for scale in (0.9, 1.1):
                    adjusted = cv2.resize(crop, None, fx=scale, fy=scale)
                    value, _, _ = cv2.QRCodeDetector().detectAndDecode(adjusted)
                    if value:
                        values.add(value)
        except cv2.error:
            continue
    if len(values) != 1:
        return {}, "conflicting_qr" if values else "unreadable_qr"
    try:
        return parse_qr(values.pop()), "readable"
    except ValueError:
        return {}, "invalid_qr"


def extract_pages(uploaded):
    """Keep original PDF objects, using rendered pixels only to decode QR."""
    uploaded.seek(0)
    raw = uploaded.read()
    uploaded.seek(0)
    is_pdf = uploaded.name.lower().endswith(".pdf")
    with pymupdf.open(
        stream=raw, filetype="pdf" if is_pdf else uploaded.name.rsplit(".", 1)[-1]
    ) as source:
        if is_pdf:
            document = source
            converted = None
        else:
            converted = pymupdf.open(stream=source.convert_to_pdf(), filetype="pdf")
            document = converted
        try:
            pages = []
            for index, page in enumerate(document):
                pix = page.get_pixmap(
                    matrix=pymupdf.Matrix(
                        min(3, 6000 / max(page.rect.width, page.rect.height)),
                        min(3, 6000 / max(page.rect.width, page.rect.height)),
                    ),
                    alpha=False,
                    colorspace=pymupdf.csRGB,
                )
                image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                    pix.height, pix.width, 3
                )
                fields, status = decode_page(cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
                with pymupdf.open() as single:
                    single.insert_pdf(document, from_page=index, to_page=index)
                    content = single.tobytes()
                pages.append((index + 1, fields, status, content))
            return raw, pages
        finally:
            if converted:
                converted.close()


def group_issues(submission, pages=None):
    pages = (
        [page for page in submission.pages.all() if not page.excluded]
        if pages is None
        else pages
    )
    expected = set(submission.assessment.expected_qr_page_labels)
    counts = Counter(page.page_label for page in pages if page.page_label)
    issues = sorted(
        set(page.qr_status for page in pages if page.qr_status != "readable")
    )
    issues += [
        "missing:" + label
        for label in sorted(expected - counts.keys(), key=label_order)
    ]
    issues += [
        "unexpected:" + label
        for label in sorted(counts.keys() - expected, key=label_order)
    ]
    issues += ["duplicate:" + label for label, count in counts.items() if count > 1]
    identities = set(
        page.suggested_enrollment_id for page in pages if page.suggested_enrollment_id
    )
    if len(identities) > 1:
        issues.append("conflicting_student")
    return issues


def ordered_pages(submission):
    return sorted(
        [page for page in submission.pages.all() if not page.excluded],
        key=lambda page: (
            label_order(page.page_label) if page.page_label else 10000,
            page.pk,
        ),
    )


def rebuild_script(submission, created_files):
    from submissions.retention import retain_file_revision

    retain_file_revision(submission)
    pages = ordered_pages(submission)
    if not pages:
        submission.file = ""
        submission.qr_review_issues = group_issues(submission)
        submission.save(update_fields=["file", "qr_review_issues"])
        return
    with pymupdf.open() as document:
        for page in pages:
            with page.file.open("rb") as stored:
                content = stored.read()
            with pymupdf.open(stream=content, filetype="pdf") as original:
                document.insert_pdf(original)
        submission.file.save(
            "group-" + uuid.uuid4().hex + ".pdf",
            ContentFile(document.tobytes()),
            save=False,
        )
        created_files.append((submission.file.storage, submission.file.name))
    submission.original_filename = "script.pdf"
    submission.qr_review_issues = group_issues(submission)
    submission.save(
        update_fields=["file", "original_filename", "qr_review_issues", "updated_at"]
    )


def create_qr_submissions(validated_data, actor):
    from distribution.services import supersede_submission_emails
    from submissions.jobs import cancel_active_jobs, enqueue_recognition
    from submissions.lifecycle import lock_active_assessment
    from submissions.models import RecognitionJob

    uploaded = validated_data["file"]
    raw, extracted = extract_pages(uploaded)
    stored_files = []
    try:
        with transaction.atomic():
            assessment = lock_active_assessment(validated_data["assessment"].pk)
            if not assessment.expected_qr_page_labels:
                raise ValidationError(
                    "QR configuration changed; reload the assessment."
                )
            upload = ScriptUpload(
                assessment=assessment, original_filename=uploaded.name
            )
            upload.file.save(
                "source-"
                + uuid.uuid4().hex
                + (
                    ".pdf"
                    if uploaded.name.lower().endswith(".pdf")
                    else "." + uploaded.name.rsplit(".", 1)[-1]
                ),
                ContentFile(raw),
                save=False,
            )
            stored_files.append((upload.file.storage, upload.file.name))
            upload.save()
            groups = {}
            group_counts = {}
            page_limit = getattr(settings, "MAX_QR_GROUP_PAGES", 100)
            for index, fields, qr_status, content in extracted:
                if fields:
                    key = ",".join(
                        fields[field]
                        for field in ("module", "date", "test", "test_number")
                    )
                    if (
                        fields["module"].casefold() != assessment.course.code.casefold()
                        or assessment.date
                        and fields["date"] != assessment.date.strftime("%Y%m%d")
                        or assessment.qr_test
                        and fields["test"] != assessment.qr_test
                    ):
                        qr_status = "conflicting_test"
                else:
                    key = "review:" + uuid.uuid4().hex
                if key not in groups:
                    submission = (
                        Submission.objects.active()
                        .filter(assessment=assessment, qr_group_key=key)
                        .first()
                    )
                    if (
                        submission is None
                        and Submission.objects.filter(
                            assessment=assessment,
                            qr_group_key=key,
                            archived_at__isnull=True,
                            superseded_at__isnull=True,
                        ).exists()
                    ):
                        raise ValidationError(
                            "Restore withdrawn class membership before adding pages to its retained QR group."
                        )
                    if submission:
                        # Parent locks serialize all intake/verification; workers use job then submission.
                        list(
                            RecognitionJob.objects.filter(
                                submission=submission,
                                status__in=RecognitionJob.ACTIVE_STATUSES,
                            ).select_for_update()
                        )
                        submission = Submission.objects.select_for_update().get(
                            pk=submission.pk
                        )
                        if submission.recognition_method != validated_data.get(
                            "recognition_method", "ocr"
                        ):
                            raise ValidationError(
                                "Existing group uses a different recognition method."
                            )
                        from submissions.retention import retain_file_revision

                        retain_file_revision(submission)
                        cancel_active_jobs(submission)
                        supersede_submission_emails(submission)
                        submission.record_status_change(
                            actor,
                            Submission.Status.PROCESSING,
                            new_enrollment=None,
                            reason="QR group received additional pages",
                        )
                        submission.pages.update(linked_enrollment=None)
                    else:
                        submission = Submission.objects.create(
                            assessment=assessment,
                            recognition_method=validated_data.get(
                                "recognition_method", "ocr"
                            ),
                            status=Submission.Status.PROCESSING,
                            qr_group_key=key,
                            qr_metadata={
                                k: v for k, v in fields.items() if k != "page_label"
                            },
                            original_filename="script.pdf",
                        )
                        SubmissionAudit.objects.create(
                            submission=submission,
                            actor=actor,
                            previous_status=None,
                            new_status=submission.status,
                            reason="QR script group uploaded",
                        )
                    groups[key] = submission
                    group_counts[key] = submission.pages.count()
                group_counts[key] += 1
                if group_counts[key] > page_limit:
                    raise ValidationError(
                        f"QR group exceeds the retained page limit ({page_limit}). Split or review the batch before uploading."
                    )
                page = ScriptPage(
                    submission=groups[key],
                    upload=upload,
                    source_page=index,
                    source_filename=uploaded.name,
                    qr_fields=fields,
                    qr_status=qr_status,
                    page_label=fields.get("page_label", ""),
                )
                page.file.save(
                    "page-" + uuid.uuid4().hex + ".pdf",
                    ContentFile(content),
                    save=False,
                )
                stored_files.append((page.file.storage, page.file.name))
                page.save()
            for submission in groups.values():
                rebuild_script(submission, stored_files)
                enqueue_recognition(submission)
            primary = next(iter(groups.values()))
            primary.upload_group_ids = [submission.pk for submission in groups.values()]
            return primary
    except Exception:
        for storage, name in stored_files:
            storage.delete(name)
        raise


def review_page(submission_id, page_id, payload, actor):
    """Explicit, audited repair of unreadable labels, duplicate pages or identity conflicts."""
    from django.shortcuts import get_object_or_404
    from django.utils import timezone

    from distribution.services import supersede_submission_emails
    from students.models import Enrollment
    from submissions.jobs import cancel_active_jobs
    from submissions.lifecycle import lock_submission_scope
    from submissions.models import RecognitionJob

    if not isinstance(payload.get("reason"), str) or not payload["reason"].strip():
        raise ValidationError("Page review requires a reason.")
    if type(payload.get("version")) is not int:
        raise ValidationError("Page review requires the current submission version.")
    if "exclude" in payload and type(payload["exclude"]) is not bool:
        raise ValidationError("exclude must be a boolean.")
    for field in (
        "destination_submission",
        "destination_version",
        "reviewed_enrollment",
    ):
        if (
            field in payload
            and payload[field] is not None
            and type(payload[field]) is not int
        ):
            raise ValidationError({field: "Use an integer."})
    fields = parse_qr(payload["qr_value"]) if "qr_value" in payload else None
    stored_files = []
    try:
        with transaction.atomic():
            lock_submission_scope(submission_id)
            source = get_object_or_404(
                Submission.objects.active(),
                pk=submission_id,
                assessment__course__owner=actor,
            )
            destination_id = payload.get("destination_submission", source.pk)
            destination = get_object_or_404(
                Submission.objects.active(),
                pk=destination_id,
                assessment_id=source.assessment_id,
            )
            if not source.qr_group_key or not destination.qr_group_key:
                raise ValidationError("Page review is only available for QR groups.")
            ids = sorted({source.pk, destination.pk})
            list(
                RecognitionJob.objects.filter(
                    submission_id__in=ids, status__in=RecognitionJob.ACTIVE_STATUSES
                )
                .order_by("pk")
                .select_for_update()
            )
            locked = {
                item.pk: item
                for item in Submission.objects.filter(pk__in=ids)
                .order_by("pk")
                .select_for_update()
            }
            source, destination = locked[source.pk], locked[destination.pk]
            if source.version != payload["version"]:
                raise ValidationError(
                    "This submission has changed. Reload and try again."
                )
            if (
                source.pk != destination.pk
                and payload.get("destination_version") != destination.version
            ):
                raise ValidationError(
                    "Moving pages requires the current destination version."
                )
            page = get_object_or_404(
                ScriptPage.objects.select_for_update(), pk=page_id, submission=source
            )
            if fields:
                metadata = {k: v for k, v in fields.items() if k != "page_label"}
                key = ",".join(
                    fields[field] for field in ("module", "date", "test", "test_number")
                )
                assessment = source.assessment
                if (
                    fields["module"].casefold() != assessment.course.code.casefold()
                    or assessment.date
                    and fields["date"] != assessment.date.strftime("%Y%m%d")
                    or assessment.qr_test
                    and fields["test"] != assessment.qr_test
                ):
                    raise ValidationError(
                        "Corrected QR metadata must match the assessment."
                    )
                if destination.qr_metadata and metadata != destination.qr_metadata:
                    raise ValidationError(
                        "The corrected QR does not belong to the destination group."
                    )
                if not destination.qr_metadata:
                    if (
                        Submission.objects.filter(
                            assessment=assessment, qr_group_key=key
                        )
                        .exclude(pk=destination.pk)
                        .exists()
                    ):
                        raise ValidationError(
                            "Move this page to the existing group instead."
                        )
                    destination.qr_metadata, destination.qr_group_key = metadata, key
                    destination.save(update_fields=["qr_metadata", "qr_group_key"])
            elif (
                destination.pk != source.pk
                and page.qr_fields
                and {k: v for k, v in page.qr_fields.items() if k != "page_label"}
                != destination.qr_metadata
            ):
                raise ValidationError(
                    "A move between different groups requires a corrected QR value."
                )
            elif destination.pk != source.pk and not page.qr_fields:
                raise ValidationError(
                    "An unreadable page requires a corrected QR value."
                )
            page.review_history = [
                *page.review_history,
                dict(
                    actor=actor.pk,
                    timestamp=timezone.now().isoformat(),
                    corrected_fields=fields,
                    destination_group=destination.pk,
                    reviewed_enrollment=payload.get(
                        "reviewed_enrollment", page.suggested_enrollment_id
                    ),
                    reason=payload["reason"].strip(),
                    previous_fields=page.qr_fields,
                    previous_group=source.pk,
                    previous_suggestion=page.suggested_enrollment_id,
                    excluded=payload.get("exclude", page.excluded),
                ),
            ]
            if fields:
                page.qr_fields, page.page_label, page.qr_status = (
                    fields,
                    fields["page_label"],
                    "readable",
                )
            if "reviewed_enrollment" in payload:
                page.suggested_enrollment = (
                    get_object_or_404(
                        Enrollment.objects.active().filter(
                            course=source.assessment.course
                        ),
                        pk=payload["reviewed_enrollment"],
                    )
                    if payload["reviewed_enrollment"] is not None
                    else None
                )
            page.submission = destination
            page.linked_enrollment = None
            page.excluded = payload.get("exclude", page.excluded)
            page.save()
            for item in locked.values():
                from submissions.retention import retain_file_revision

                retain_file_revision(item)
                cancel_active_jobs(item)
                supersede_submission_emails(item)
                item.record_status_change(
                    actor,
                    Submission.Status.PROCESSING,
                    new_enrollment=None,
                    reason="QR page review: " + payload["reason"].strip(),
                )
                item.pages.update(linked_enrollment=None)
                rebuild_script(item, stored_files)
                item.record_status_change(
                    actor,
                    Submission.Status.NEEDS_VERIFICATION,
                    reason="QR page review requires renewed verification",
                )
            source.refresh_from_db()
            return source
    except Exception:
        for storage, name in stored_files:
            storage.delete(name)
        raise
