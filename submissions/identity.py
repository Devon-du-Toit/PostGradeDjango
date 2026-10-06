def enrollment_identity(enrollment):
    if enrollment is None:
        return {}
    return {
        "origin": "transition",
        "enrollment_id": enrollment.pk,
        "student_id": enrollment.student_id,
        "student_number": enrollment.student.student_number,
        "course_id": enrollment.course_id,
    }
