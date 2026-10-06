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


def build_script_email(submission):
    student = submission.enrollment.student
    return (
        f"PostGrade script: {submission.assessment.name}",
        f"Hi {student.first_name},\n\n"
        f"Your verified script for {submission.assessment.name} is attached.\n\n"
        "Regards,\nPostGrade",
    )
