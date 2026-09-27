from django.core.mail import send_mail


def send_student_email(student, subject, message):
    if not student.email:
        raise ValueError("Student does not have an email address.")

    send_mail(
        subject=subject,
        message=message,
        from_email=None,
        recipient_list=[student.email],
    )


def build_result_email(result):
    student = result.enrollment.student
    assessment = result.assessment

    percentage = round(
        (result.mark / assessment.max_mark) * 100,
        2,
    )

    subject = f"PostGrade result: {assessment.name}"

    message = (
        f"Hi {student.first_name},\n\n"
        f"Your result for {assessment.name} is:\n\n"
        f"{result.mark} / {assessment.max_mark}\n"
        f"{percentage}%\n\n"
        f"Regards,\n"
        f"PostGrade"
    )

    return subject, message


def send_result_email(result):
    student = result.enrollment.student
    subject, message = build_result_email(result)

    send_student_email(
        student=student,
        subject=subject,
        message=message,
    )