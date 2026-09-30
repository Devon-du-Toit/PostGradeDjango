from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class OptInPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def paginate_queryset(self, queryset, request, view=None):
        self.empty_page = False
        requested_page = request.query_params.get(self.page_query_param)
        page_size = self.get_page_size(request)
        if requested_page is not None and page_size is not None:
            try:
                requested_page = int(requested_page)
            except ValueError:
                pass
            else:
                paginator = self.django_paginator_class(queryset, page_size)
                if requested_page > paginator.num_pages:
                    self.empty_page = True
                    self.count = paginator.count
                    return []

        return super().paginate_queryset(queryset, request, view)

    def get_paginated_response(self, data):
        if self.empty_page:
            return Response({
                "count": self.count,
                "next": None,
                "previous": None,
                "results": data,
            })
        return super().get_paginated_response(data)