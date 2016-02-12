# -*- coding: utf-8 -*-
from django import forms

ASC = 'asc'
DESC = 'desc'
SORT_DIRS = (
    (ASC, ASC),
    (DESC, DESC),
)


class DatatablesForm(forms.Form):
    '''
    Datatables server side processing Form

    See: http://www.datatables.net/usage/server-side
    '''
    def __init__(self, *args, **kwargs):
        super(DatatablesForm, self).__init__(*args, **kwargs)

        i = 0
        while i < len(args[0]):

            if args[0].get('columns[%s][data]' % i, None) is not None:
                self.fields['columns[%s][data]' % i] = forms.CharField(required=False)
                self.fields['columns[%s][name]' % i] = forms.CharField(required=False)
                self.fields['columns[%s][orderable]' % i] = forms.BooleanField(required=False)
                self.fields['columns[%s][searchable]' % i] = forms.BooleanField(required=False)
                self.fields['columns[%s][search][regex]' % i] = forms.BooleanField(required=False)
                self.fields['columns[%s][search][value]' % i] = forms.CharField(required=False)

            if args[0].get('order[%s][dir]' % i, None) is not None:
                self.fields['order[%s][dir]' % i] = forms.CharField(required=False)
                self.fields['order[%s][column]' % i] = forms.CharField(required=False)

            i += 1

        self.fields['search[regex]'] = forms.BooleanField(required=False)
        self.fields['search[value]'] = forms.CharField(required=False)
        self.fields['length'] = forms.CharField(required=False)
        self.fields['start'] = forms.CharField(required=False)
        self.fields['draw'] = forms.CharField(required=False)

