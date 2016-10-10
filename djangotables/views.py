# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import operator
import json
import io
import re
import csv
import types
import datetime
import pytz
import hashlib

from operator import or_

from django.core.paginator import Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.core.exceptions import PermissionDenied
from django.utils.six import text_type
from django.utils.six.moves import reduce, xrange
from django.views.generic import View
from djangotables.mixins.MultiObjectMixin import MultiObjectMixin

from djangotables.forms import DatatablesForm, DESC


RE_FORMATTED = re.compile(r'\{(\w+)\}')

#: SQLite unsupported field types for regex lookups
UNSUPPORTED_REGEX_FIELDS = (
    models.IntegerField,
    models.BooleanField,
    models.NullBooleanField,
    models.FloatField,
    models.DecimalField,
)


def get_real_field(model, field_name):
    '''
    Get the real field from a model given its name.

    Handle nested models recursively (aka. ``__`` lookups)
    '''
    parts = field_name.split('__')
    field = model._meta.get_field(parts[0])
    if len(parts) == 1:
        return model._meta.get_field(field_name)
    elif isinstance(field, models.ForeignKey):
        return get_real_field(field.rel.to, '__'.join(parts[1:]))
    else:
        raise Exception('Unhandled field: %s' % field_name)


class DatatablesView(MultiObjectMixin, View):
    model = None
    _db_fields = None
    fields = []
    sFilters = {}
    timezone = pytz.UTC
    view_access = True
    download_access = False
    download = False
    download_type = 'csv'
    download_filename = ''

    def load_filters(self, request_data):
        try:
            self.sFilters = json.loads('[' + request_data['sFilters'] + ']')[0]

        except:
            self.sFilters = {}

        if len(self.sFilters) == 0:
            return HttpResponseBadRequest()

    def check_auth_list(self, request, access_list):
        auth = False
        if (
            isinstance(access_list, bool) and
            access_list is True
        ):
            auth = True

        elif isinstance(access_list, list):
            user_groups = request.user.groups.all()
            for user_group in user_groups:
                if user_group.pk in access_list:
                    auth = True
                    break

        return auth

    def check_auth(self, request, request_data):
        auth = False
        if request.user:
            if self.download:
                auth = self.check_auth_list(request, self.download_access)
            else:
                auth = self.check_auth_list(request, self.view_access)

        if not auth:
            raise PermissionDenied

        else:
            self.uid = request.user.pk
            if request_data.get('mSearch', None) is not None:
                self.sFilters['user__id'] = [self.uid]

    def custom_processing(self, request_data, **kwargs):
        pass

    def process(self, request):
        if request.method == 'GET':
            request_data = request.GET.dict()
        else:
            request_data = request.POST.dict()
        self.load_filters(request_data)
        self.check_auth(request, request_data)
        self.custom_processing(request_data)
        return self.process_dt_response(request_data)

    def get(self, request, *args, **kwargs):
        if not request.GET.__contains__('download'):
            return HttpResponseBadRequest()

        else:
            self.download = True
            self.download_filename = str(self.model) + '_' +  datetime.datetime.now().replace(microsecond=0).isoformat()
            return self.process(request)

    def post(self, request, *args, **kwargs):
        if not request.is_ajax():
            return HttpResponseBadRequest()

        else:
            return self.process(request)

    def process_dt_response(self, data):
        self.form = DatatablesForm(data)
        if self.form.is_valid():
            self.object_list = self.get_queryset().all()
            return self.render_to_response(self.form)
        else:
            return HttpResponseBadRequest()

    def get_db_fields(self):
        if not self._db_fields:
            self._db_fields = []
            fields = self.fields.values() if isinstance(self.fields, dict) else self.fields
            for field in fields:
                if RE_FORMATTED.match(field):
                    self._db_fields.extend(RE_FORMATTED.findall(field))
                else:
                    self._db_fields.append(field)
        return self._db_fields

    @property
    def dt_data(self):
        return self.form.cleaned_data

    def get_field(self, index):
        if isinstance(self.fields, dict):
            return self.fields[self.dt_data['columns[%s][data]' % index]]
        else:
            return self.fields[index]

    def can_regex(self, field):
        '''Test if a given field supports regex lookups'''
        from django.conf import settings
        if settings.DATABASES['default']['ENGINE'].endswith('sqlite3'):
            return not isinstance(get_real_field(self.model, field), UNSUPPORTED_REGEX_FIELDS)
        else:
            return True

    def get_orders(self):
        '''Get ordering fields for ``QuerySet.order_by``'''
        orders, dt_orders = [], []

        i = 0
        while i < len(self.dt_data):

            if self.dt_data.get('order[%s][column]' % i, None) is not None:

                dt_orders.append((
                    self.dt_data['order[%s][column]' % i],
                    self.dt_data['order[%s][dir]' % i]
                ))

            else:
                break

            i += 1

        for field_idx, field_dir in dt_orders:
            direction = '-' if field_dir == DESC else ''
            if hasattr(self, 'order[%s][column]' % field_idx):
                method = getattr(self, 'order[%s][column]' % field_idx)
                result = method(direction)
                if isinstance(result, (bytes, text_type)):
                    orders.append(result)
                else:
                    orders.extend(result)
            else:
                field = self.get_field(field_idx)
                if RE_FORMATTED.match(field):
                    tokens = RE_FORMATTED.findall(field)
                    orders.extend(['%s%s' % (direction, token) for token in tokens])
                else:
                    orders.append('%s%s' % (direction, field))
        return orders

    def global_search(self, queryset):
        '''Filter a queryset with global search'''
        search = self.dt_data['search']['value']
        if search:
            if self.dt_data['search']['regex']:
                criterions = [
                    Q(**{'%s__iregex' % field: search})
                    for field in self.get_db_fields()
                    if self.can_regex(field)
                ]
                if len(criterions) > 0:
                    search = reduce(or_, criterions)
                    queryset = queryset.filter(search)
            else:
                for term in search.split():
                    criterions = (Q(**{'%s__icontains' % field: term}) for field in self.get_db_fields())
                    search = reduce(or_, criterions)
                    queryset = queryset.filter(search)
        return queryset

    def column_search(self, queryset):
        '''Filter a queryset with column search'''

        i = 0
        while i < len(self.dt_data):

            if self.dt_data.get('columns[%s][search][value]' % i, None) is not None:

                search = self.dt_data['columns[%s][search][value]' % i]
                if search:

                    if hasattr(self, 'search_col_%s' % i):
                        custom_search = getattr(self, 'search_col_%s' % i)
                        queryset = custom_search(search, queryset)

                    else:
                        fieldT = self.get_field(i)
                        fields = RE_FORMATTED.findall(fieldT) if RE_FORMATTED.match(fieldT) else [fieldT]
                        if self.dt_data['columns[%s][search][regex]' % i]:

                            criterions = [Q(**{'%s__iregex' % field: search}) for field in fields if self.can_regex(field)]
                            if len(criterions) > 0:
                                search = reduce(or_, criterions)
                                queryset = queryset.filter(search)

                        else:
                            for term in search.split():
                                criterions = (Q(**{'%s__icontains' % field: term}) for field in fields)
                                search = reduce(or_, criterions)
                                queryset = queryset.filter(search)

            else:
                break

            i += 1

        return queryset

    def filter_search(self, qs):
        kwargs = {}
        for key, value in self.sFilters.iteritems():
            sKey = key.split(':')

            filterList = True
            if not isinstance(value, list):
                value = [value]
                filterList = False

            for index, item in enumerate(value):
                if isinstance(item, str) or isinstance(item, unicode):
                    try:
                        value[index] = self.timezone.localize(
                            datetime.datetime.strptime(
                                item, '%m/%d/%Y %I:%M %p'
                            )
                        ).astimezone(
                            pytz.utc
                        ).replace(
                            tzinfo=None
                        )

                    except:
                        if item.isdigit():
                            value[index] = int(item)

            if len(sKey) > 1:  # range search
                if sKey[1] == 'from':
                    kwargs[sKey[0] + '__gte'] = value[0]
                elif sKey[1] == 'to':
                    kwargs[sKey[0] + '__lt'] = value[0]

            elif filterList:  # list search
                args = []
                for i in value:
                    args.append(Q(**{sKey[0]: i}))

                qs = qs.filter(reduce(operator.or_, args))

            elif isinstance(value[0], types.BooleanType) or isinstance(
                value[0], types.IntType
            ):  # boolean search
                if value[0] is True:
                    kwargs[sKey[0] + '__gt'] = 0

                else:
                    kwargs[sKey[0]] = 0

            else:  # text search
                if sKey[0].endswith('sha256'):
                    kwargs[sKey[0]] = hashlib.sha256(value[0]).hexdigest()
                else:
                    kwargs[sKey[0] + '__icontains'] = value[0]

        if len(kwargs) > 0:
            qs = qs.filter(**kwargs)

        return qs

    def adjust_search(self, qs):
        return qs

    def get_queryset(self):
        qs = super(DatatablesView, self).get_queryset()
        #qs = self.global_search(qs)
        #qs = self.column_search(qs)
        qs = self.filter_search(qs)
        return self.adjust_search(qs).order_by(*self.get_orders())

    def get_page(self, form):
        if self.download:
            start_index = 0
            page_size = len(self.object_list)

        else:
            start_index = int(form.cleaned_data['start'])
            page_size = int(form.cleaned_data['length'])

        paginator = Paginator(self.object_list, page_size)
        num_page = (start_index / page_size) + 1
        return paginator.page(num_page)

    def get_rows(self, rows):
        return [self.get_row(row) for row in rows]

    def get_row(self, row):
        ret = {}
        for key, value in self.fields.items():
            if RE_FORMATTED.match(value):
                ret[key] = re.sub(
                    '\{([^}]*)\}',
                    lambda x: self.get_row_field(row, x.groups()[0]),
                    value
                )

            else:
                ret[key] = self.get_row_field(row, value)

        return ret

    def get_row_field(self, row, field):
        obj, count, secs = row, 0, field.split('__')
        while count < len(secs):
            if count == (len(secs) - 1):
                return self.get_field_value(obj, secs[count])
            else:
                obj = getattr(obj, secs[count])
                count += 1

    def get_field_value(self, obj, field):
        if hasattr(obj, field):
            val = getattr(obj, field)
            if str(type(val)).startswith('<type'):
                return val
            elif hasattr(val, 'id'):
                return getattr(val, 'id')
            else:
                return "ERROR"
        else:
            return None

    def format_response(self, dList):
        return (dList, [])

    def render_to_response(self, form, **kwargs):
        page = self.get_page(form)
        dList, headers = self.format_response(self.get_rows(page.object_list))
        if self.download:
            if self.download_type == 'csv':
                output = io.BytesIO()
                w = csv.writer(output)
                header = False
                for d in dList:
                    keys, row = [], []
                    for i in d:
                        try:
                            row.append(str(d[i]).encode('utf-8'))

                        except:
                            row.append(d[i].encode('utf-8'))

                        keys.append(i)
    
                    if not header:
                        if len(headers) > 0:
                            keys = headers
                        w.writerow(keys)
                        header = True
    
                    w.writerow(row)
    
                response = HttpResponse(
                    output.getvalue(),
                    content_type='text/csv'
                )

            response[
                'Content-Disposition'
            ] = 'attachment; filename="' + self.download_filename + '.' + self.download_type + '"'

            return response

        else:
            return HttpResponse(
                json.dumps({
                    'recordsTotal': page.paginator.count,
                    'recordsFiltered': page.paginator.count,
                    'draw': int(form.cleaned_data['draw']),
                    'data': dList
                }, cls=DjangoJSONEncoder),
                content_type='application/json'
            )

