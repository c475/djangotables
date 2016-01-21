from django.views.generic.list import MultipleObjectMixin


class MultiObjectMixin(MultipleObjectMixin):

    """
    Modified django.views.generic.list.MultipleObjectMixin,
    so you can specify a database to query, instead of just 'default'
    """

    def get_queryset(self):
        if self.queryset is not None:
            queryset = self.queryset
            if isinstance(queryset, QuerySet):
                queryset = queryset.all()
        elif self.model is not None:
            if hasattr(self, 'database'):
                queryset = self.model._default_manager.using(self.database).all()
            else:
                queryset = self.model._default_manager.all()
        else:
            raise ImproperlyConfigured(
                "%(cls)s is missing a QuerySet. Define "
                "%(cls)s.model, %(cls)s.queryset, or override "
                "%(cls)s.get_queryset()." % {
                    'cls': self.__class__.__name__
                }
            )
        ordering = self.get_ordering()
        if ordering:
            if isinstance(ordering, six.string_types):
                ordering = (ordering,)
            queryset = queryset.order_by(*ordering)

        return queryset
