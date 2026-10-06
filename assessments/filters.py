from assessments.models import Assessment


def owned_assessments(request):
    if request is None:
        return Assessment.objects.none()
    return Assessment.objects.filter(course__owner=request.user)
