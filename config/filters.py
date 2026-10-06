import django_filters


class ChoiceInFilter(django_filters.BaseInFilter, django_filters.ChoiceFilter):
    # ?status=a,b: comma-separated, and every value must be a valid choice.
    # axios sends arrays as status[]=a&status[]=b, which Django does not
    # read as a list, so one comma-separated value works from any client.
    pass
