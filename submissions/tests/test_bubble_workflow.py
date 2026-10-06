from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from assessments.models import Assessment
from courses.models import Course
from students.models import Enrollment, Student
from submissions.jobs import process_next_job
from submissions.models import RecognitionAttempt, Submission
from submissions.recognition.service import recognize_submission
from submissions.tests.bubble_helpers import bubble_image, png_bytes
from submissions.tests.helpers import TemporaryMediaMixin


class BubbleWorkflowTests(TemporaryMediaMixin, TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="bubble@example.invalid", password="testpass123")
        self.course = Course.objects.create(owner=self.user, code="BUB", name="Synthetic", year=2026, semester=1)
        self.assessment = Assessment.objects.create(course=self.course, name="Synthetic", max_mark=100, weight=10)
        self.student = Student.objects.create(owner=self.user, student_number="01234567", first_name="Synthetic", last_name="Student")
        self.enrollment = Enrollment.objects.create(course=self.course, student=self.student)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def upload(self, method="bubble", image=None):
        return self.client.post('/api/submissions/', {
            'assessment': self.assessment.pk, 'recognition_method': method,
            'file': SimpleUploadedFile('synthetic.png', png_bytes(image or bubble_image()), content_type='image/png'),
        }, format='multipart')

    @patch('submissions.recognition.service.locate_student_number', side_effect=AssertionError('OCR must never run for bubbles'))
    def test_upload_worker_and_protected_evidence_use_bubbles_only(self, ocr):
        response = self.upload()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['recognition_method'], 'bubble')
        self.assertTrue(process_next_job())
        submission = Submission.objects.get(pk=response.data['id'])
        self.assertEqual(submission.status, 'matched')
        self.assertEqual(submission.enrollment, self.enrollment)
        evidence = self.client.get(f'/api/submissions/{submission.pk}/').data['recognition']
        self.assertEqual(evidence['method'], 'bubble')
        self.assertEqual(evidence['raw_candidate'], '01234567')
        self.assertEqual(evidence['processing_version'], 'bubble-1')
        self.assertEqual(evidence['template_version'], 'nwu-eight-standard-1')
        self.assertEqual(len(evidence['column_scores']), 8)
        self.assertEqual(evidence['raw_text'], '')
        image = self.client.get(evidence['region_image_url'])
        self.assertEqual(image.status_code, 200)
        other = get_user_model().objects.create_user(email='other@example.invalid', password='testpass123')
        self.client.force_authenticate(user=other)
        self.assertEqual(self.client.get(evidence['region_image_url']).status_code, 404)
        ocr.assert_not_called()

    def test_matching_is_exact_and_limited_to_this_course(self):
        other_course = Course.objects.create(owner=self.user, code='OTHER', name='Other', year=2026, semester=1)
        self.enrollment.course = other_course
        self.enrollment.save()
        response = self.upload()
        process_next_job()
        submission = Submission.objects.get(pk=response.data['id'])
        self.assertEqual(submission.status, 'needs_verification')
        self.assertIsNone(submission.enrollment)
        self.assertEqual(submission.recognition_attempts.first().outcome, 'no_match')

    def test_near_number_never_fuzzy_matches(self):
        response = self.upload(image=bubble_image('01234568', written='01234567'))
        process_next_job()
        submission = Submission.objects.get(pk=response.data['id'])
        self.assertIsNone(submission.enrollment)
        self.assertEqual(submission.status, 'needs_verification')

    def test_ambiguous_columns_require_manual_verification_even_for_enrolled_digits(self):
        fills = {column: [column] for column in range(8)}
        fills[0] = [0, 9]
        response = self.upload(image=bubble_image(fills=fills, written='01234567'))
        process_next_job()
        submission = Submission.objects.get(pk=response.data['id'])
        self.assertEqual(submission.status, 'needs_verification')
        self.assertIsNone(submission.enrollment)
        self.assertEqual(submission.recognition_attempts.first().raw_candidate, 'X1234567')

    def test_retry_retains_method_and_cannot_change_it_silently(self):
        response = self.upload(image=bubble_image(missing_marker=True))
        process_next_job()
        submission = Submission.objects.get(pk=response.data['id'])
        changed = self.client.patch(f'/api/submissions/{submission.pk}/', {'recognition_method': 'ocr', 'version': submission.version})
        self.assertEqual(changed.status_code, 400)
        self.assertEqual(self.client.post(f'/api/submissions/{submission.pk}/retry-recognition/').status_code, 202)
        submission.refresh_from_db()
        self.assertEqual(submission.recognition_method, 'bubble')

    def test_invalid_method_rejected_and_legacy_upload_defaults_to_ocr(self):
        self.assertEqual(self.upload('guess').status_code, 400)
        data = {'assessment': self.assessment.pk, 'file': SimpleUploadedFile('synthetic.png', png_bytes(bubble_image()), content_type='image/png')}
        response = self.client.post('/api/submissions/', data, format='multipart')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['recognition_method'], 'ocr')

    def test_capabilities_requires_authentication_and_advertises_bubbles(self):
        response = self.client.get('/api/submissions/recognition-methods/')
        self.assertEqual([method['value'] for method in response.data['methods']], ['ocr', 'bubble'])
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get('/api/submissions/recognition-methods/').status_code, 401)
