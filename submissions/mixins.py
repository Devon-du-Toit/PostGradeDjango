class StableOrderingMixin:
    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        current_order = list(queryset.query.order_by)
        if "id" not in current_order and "-id" not in current_order:
            queryset = queryset.order_by(*current_order, "id")
        return queryset