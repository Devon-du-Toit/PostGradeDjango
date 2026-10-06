from courses.models import Course


def owned_courses(request):
    # Choices for course filters: only the requesting lecturer's courses,
    # so another lecturer's course ID is rejected like a missing one.
    if request is None:
        return Course.objects.none()
    return Course.objects.active().filter(owner=request.user)
