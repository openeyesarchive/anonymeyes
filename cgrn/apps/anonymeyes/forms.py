from django import forms
from django.http import HttpResponseRedirect
from django.core.mail import send_mail
from django.template.loader import get_template
from django.template import Context
from django.conf import settings
from captcha.fields import ReCaptchaField
from apps.anonymeyes.models import Patient, Management, Outcome, \
    VisualAcuityReading, VisualAcuityMethod, Diagnosis, DiagnosisGroup, \
    UserProfile, EthnicGroup
from form_utils.forms import BetterModelForm
from itertools import groupby
import datetime

class GroupedModelChoiceIterator(forms.models.ModelChoiceIterator):
    def __iter__(self):
        if self.field.empty_label is not None:
            yield (u"", self.field.empty_label)
        if self.field.cache_choices:
            if self.field.choice_cache is None:
                self.field.choice_cache = [
                    (self.field.group_label(group), [self.choice(ch) for ch in choices])
                        for group, choices in groupby(self.queryset.all(),
                            key=lambda row: getattr(row, self.field.group_by_field))
                ]
            for choice in self.field.choice_cache:
                yield choice
        else:
            for group, choices in groupby(self.queryset.all(),
                    key=lambda row: getattr(row, self.field.group_by_field)):
                yield (self.field.group_label(group), [self.choice(ch) for ch in choices])

class GroupedModelChoiceField(forms.ModelChoiceField):
    def __init__(self, queryset, group_by_field, group_label=None, *args, **kwargs):
        """
        group_by_field is the name of a field on the model
        group_label is a function to return a label for each choice group
        """
        super(GroupedModelChoiceField, self).__init__(queryset, *args, **kwargs)
        self.group_by_field = group_by_field
        if group_label is None:
            self.group_label = lambda group: group
        else:
            self.group_label = group_label
    
    def _get_choices(self):
        """
        Exactly as per ModelChoiceField except returns new iterator class
        """
        if hasattr(self, '_choices'):
            return self._choices
        return GroupedModelChoiceIterator(self)
    choices = property(_get_choices, forms.ModelChoiceField._set_choices)

class ProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        exclude = ('user',)
    
class ContactForm(forms.Form):
    name = forms.CharField()
    email = forms.EmailField()
    message = forms.CharField(widget=forms.Textarea)
    
    def send_email(self):
        message = get_template('anonymeyes/message.txt')
        d = Context(self.cleaned_data)
        send_mail('Message from CGRN contact form', message.render(d), settings.CONTACT_SENDER,
                  settings.CONTACT_RECIPIENTS)

class CaptchaContactForm(ContactForm):
    captcha = ReCaptchaField()

class PatientForm(BetterModelForm):
    diagnosis_group_right = forms.ModelChoiceField(queryset=DiagnosisGroup.objects.all(), widget=forms.Select(attrs={'class':'diagnosisgroup', 'data-side':'right'}))
    diagnosis_group_left = forms.ModelChoiceField(queryset=DiagnosisGroup.objects.all(), widget=forms.Select(attrs={'class':'diagnosisgroup', 'data-side':'left'}))
    ethnic_group = GroupedModelChoiceField(queryset=EthnicGroup.objects.all(), group_by_field='group')
    
    class Meta:
        model = Patient
        fieldsets = [
                     ('patient', {
                                  'fields': [ 'sex', 'dob_day', 'dob_month',
                                             'dob_year', 'postcode', 'health_care',
                                             'ethnic_group', 'ethnic_group_comments',
                                             'consanguinity', ],
                                  }),
                     ('baseline', {
                                   'fields': [ 'visual_acuity_date', 'diagnosis_group_right',
                                              'diagnosis_right', 'diagnosis_group_left',
                                              'diagnosis_left', 'comments' ],
                                   }),
                     ('visual_acuity', {
                                   'fields': [ 'visual_acuity_method',
                                               'visual_acuity_right', 'visual_acuity_correction_right',
                                               'visual_acuity_left', 'visual_acuity_correction_left',
                                               'visual_acuity_both', 'visual_acuity_correction_both', ],
                                   }),
                     ('iop', {
                                   'fields': [ 'iop_control', 'iop_right', 'iop_left', 'tonometry', 'eua'],
                                   }),
                     ('lens', {
                                   'fields': [ 'lens_status_right', 'lens_extraction_date_right',
                                              'lens_status_left', 'lens_extraction_date_left', ],
                                   }),
                     ]
        widgets = {
                   'postcode': forms.TextInput(attrs={'size':'10'}),
                   'dob_day': forms.TextInput(attrs={'size':'10'}),
                   'dob_year': forms.TextInput(attrs={'size':'10'}),
                   'diagnosis_right': forms.Select(attrs={'class':'diagnosis', 'data-side':'right'}),
                   'diagnosis_left': forms.Select(attrs={'class':'diagnosis', 'data-side':'left'}),
                   'comments': forms.Textarea(attrs={'rows':1, 'class':'autosize'}),
                   'lens_extraction_date_right': forms.DateInput(attrs={'class':'datepicker past'}),
                   'lens_extraction_date_left': forms.DateInput(attrs={'class':'datepicker past'}),
                   'visual_acuity_date': forms.DateInput(attrs={'class':'datepicker past'}),
                   'visual_acuity_method': forms.Select(attrs={'class':'visualacuitymethod'}),
                   'visual_acuity_right': forms.Select(attrs={'class':'visualacuity'}),
                   'visual_acuity_left': forms.Select(attrs={'class':'visualacuity'}),
                   'visual_acuity_both': forms.Select(attrs={'class':'visualacuity'}),
                   'visual_acuity_correction_right': forms.Select(attrs={'class':'visualacuitycorrection'}),
                   'visual_acuity_correction_left': forms.Select(attrs={'class':'visualacuitycorrection'}),
                   'visual_acuity_correction_both': forms.Select(attrs={'class':'visualacuitycorrection'}),
                   'iop_right': forms.TextInput(attrs={'class': 'small', 'size':'10'}),
                   'iop_left': forms.TextInput(attrs={'class': 'small', 'size':'10'}),
        }
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None) # Set request for access by DOB clean methods
        super(PatientForm, self).__init__(*args, **kwargs)
        
        # Filter VisualAcuityReading choices depending upon selected method
        if self.is_bound:
            prefix = self.prefix+'-' if self.prefix else ''
            visual_acuity_method_id = self.data[prefix+'visual_acuity_method']
        else:
            visual_acuity_method_id = 'visual_acuity_method' in self.initial and self.initial['visual_acuity_method']
        if visual_acuity_method_id:
            scale_id=VisualAcuityMethod.objects.get(pk=visual_acuity_method_id).scale_id
            filtered=VisualAcuityReading.objects.filter(scale_id=scale_id)
        else:
            filtered=VisualAcuityReading.objects.none()
        for side in ['right', 'left', 'both']:
            self.fields['visual_acuity_'+side].queryset=filtered

        # Set diagnosis group and filter diagnosis choices
        for side in ['right', 'left']:
            if self.is_bound:
                prefix = self.prefix+'-' if self.prefix else ''
                diagnosis_id = self.data[prefix+'diagnosis_'+side]
                diagnosis_group_id = self.data[prefix+'diagnosis_group_'+side]
            elif 'diagnosis_'+side in self.initial:
                diagnosis_id = self.initial['diagnosis_'+side]
                diagnosis_group_id=Diagnosis.objects.get(pk=diagnosis_id).group_id
            else:
                diagnosis_id = None
                diagnosis_group_id = None
            if diagnosis_group_id:
                self.fields['diagnosis_'+side].queryset=Diagnosis.objects.filter(group_id=diagnosis_group_id)
                self.fields['diagnosis_group_'+side].initial = diagnosis_group_id
            else:
                self.fields['diagnosis_'+side].queryset=Diagnosis.objects.none()
        
    def clean_lens_extraction_date_right(self):
        lens_extraction_date_right = self.cleaned_data.get('lens_extraction_date_right')
        lens_status_right = self.cleaned_data.get('lens_status_right')
        if lens_status_right and lens_status_right.name != 'Aphakia' and lens_status_right.name != 'Pseudophakia':
            return None
        return lens_extraction_date_right
    
    def clean_lens_extraction_date_left(self):
        lens_extraction_date_left = self.cleaned_data.get('lens_extraction_date_left')
        lens_status_left = self.cleaned_data.get('lens_status_left')
        if lens_status_left and lens_status_left.name != 'Aphakia' and lens_status_left.name != 'Pseudophakia':
            return None
        return lens_extraction_date_left

    def clean_visual_acuity_correction_right(self):
        visual_acuity_correction_right = self.cleaned_data.get('visual_acuity_correction_right')
        visual_acuity_right = self.cleaned_data.get('visual_acuity_right')
        if visual_acuity_right and visual_acuity_right.not_recorded:
            return None
        if not visual_acuity_correction_right:
            raise forms.ValidationError("This field is required")
        return visual_acuity_correction_right
    
    def clean_visual_acuity_correction_left(self):
        visual_acuity_correction_left = self.cleaned_data.get('visual_acuity_correction_left')
        visual_acuity_left = self.cleaned_data.get('visual_acuity_left')
        if visual_acuity_left and visual_acuity_left.not_recorded:
            return None
        if not visual_acuity_correction_left:
            raise forms.ValidationError("This field is required")
        return visual_acuity_correction_left
    
    def clean_visual_acuity_correction_both(self):
        visual_acuity_correction_both = self.cleaned_data.get('visual_acuity_correction_both')
        visual_acuity_both = self.cleaned_data.get('visual_acuity_both')
        if visual_acuity_both and visual_acuity_both.not_recorded:
            return None
        if not visual_acuity_correction_both:
            raise forms.ValidationError("This field is required")
        return visual_acuity_correction_both
    
    def clean_dob_month(self):
        dob_month = self.cleaned_data.get('dob_month')
        dob_day = self.cleaned_data.get('dob_day')
        precision = self.request.user.get_profile().dob_precision
        if ((precision and precision.name != 'Year') or dob_day) and dob_month == None:
            raise forms.ValidationError("DOB month required")
        return dob_month

    def clean_dob_day(self):
        dob_day = self.cleaned_data.get('dob_day')
        precision = self.request.user.get_profile().dob_precision
        if precision and precision.name == 'Day' and dob_day == None:
            raise forms.ValidationError("DOB day required")
        return dob_day

    def clean_ethnic_group_comments(self):
        ethnic_group = self.cleaned_data.get('ethnic_group')
        ethnic_group_comments = self.cleaned_data.get('ethnic_group_comments')
        if ethnic_group.requires_comment and not ethnic_group_comments.strip():
            raise forms.ValidationError("Selected ethnic group requires comment")
        return ethnic_group_comments

    def clean_comments(self):
        comments = self.cleaned_data.get('comments')
        diagnosis_left = self.cleaned_data.get('diagnosis_left')
        diagnosis_right = self.cleaned_data.get('diagnosis_right')
        if (diagnosis_left.requires_comment or diagnosis_right.requires_comment) \
        and not comments.strip():
            raise forms.ValidationError("Selected diagnosis requires comment")
        return comments

    def clean(self):
        cleaned_data = super(PatientForm, self).clean()
        dob_day = int(cleaned_data.get("dob_day") or 1)
        dob_month = int(cleaned_data.get("dob_month") or 1)
        dob_year = int(cleaned_data.get("dob_year") or 0)
        try:
            dob = datetime.datetime(dob_year, dob_month, dob_day)
        except ValueError:
            raise forms.ValidationError("DOB is not valid")
        return cleaned_data
    
class PatientManagementForm(forms.ModelForm):
    class Meta:
        model = Management
        widgets = {
                   'date': forms.DateInput(attrs={'class':'datepicker past'}),
                   'comments': forms.Textarea(attrs={'rows':1, 'class':'autosize'}),
        }
        exclude = { 'patient', 'created_by', 'updated_by', }
        
    def clean_surgery(self):
        surgery = self.cleaned_data.get('surgery')
        type = self.cleaned_data.get('type')
        if type and type.name == 'Surgery' and not surgery:
            raise forms.ValidationError("Surgery detail required")
        elif type and type.name != 'Surgery':
            return None
        return surgery

    def clean_complication(self):
        complication = self.cleaned_data.get('complication')
        type = self.cleaned_data.get('type')
        if type and type.name == 'Complication' and not complication:
            raise forms.ValidationError("Complication detail required")
        elif type and type.name != 'Complication':
            return None
        return complication

    def clean_adjuvant(self):
        adjuvant = self.cleaned_data.get('adjuvant')
        surgery = self.cleaned_data.get('surgery')
        if surgery and surgery.adjuvant and not adjuvant:
            raise forms.ValidationError("Adjuvant detail required")
        elif surgery and not surgery.adjuvant:
            return None
        return adjuvant

    def clean_surgery_stage(self):
        surgery_stage = self.cleaned_data.get('surgery_stage')
        surgery = self.cleaned_data.get('surgery')
        if surgery and surgery.stage and not surgery_stage:
            raise forms.ValidationError("Surgery stage detail required")
        elif surgery and not surgery.stage:
            return None
        return surgery_stage

    def clean_comments(self):
        comments = self.cleaned_data.get('comments')
        surgery = self.cleaned_data.get('surgery')
        complication = self.cleaned_data.get('complication')
        if ((surgery and surgery.requires_comment) or (complication and complication.requires_comment)) \
        and not comments.strip():
            if surgery:
                raise forms.ValidationError("Selected surgery requires comment")
            elif complication:
                raise forms.ValidationError("Selected complication requires comment")
        return comments

class PatientOutcomeForm(forms.ModelForm):
    class Meta:
        model = Outcome
        widgets = {
                   'date': forms.DateInput(attrs={'class':'datepicker past'}),
                   'visual_acuity_method': forms.Select(attrs={'class':'visualacuitymethod'}),
                   'visual_acuity_right': forms.Select(attrs={'class':'visualacuity'}),
                   'visual_acuity_left': forms.Select(attrs={'class':'visualacuity'}),
                   'visual_acuity_both': forms.Select(attrs={'class':'visualacuity'}),
                   'visual_acuity_correction_right': forms.Select(attrs={'class':'visualacuitycorrection'}),
                   'visual_acuity_correction_left': forms.Select(attrs={'class':'visualacuitycorrection'}),
                   'visual_acuity_correction_both': forms.Select(attrs={'class':'visualacuitycorrection'}),
                   'iop_left': forms.TextInput(attrs={'class':'small'}),
                   'iop_right': forms.TextInput(attrs={'class':'small'}),
        }
        exclude = { 'patient', 'created_by', 'updated_by', }

    def __init__(self, *args, **kwargs):
        super(PatientOutcomeForm, self).__init__(*args, **kwargs)
        
        # Filter VisualAcuityReading choices depending upon selected method
        if self.is_bound:
            prefix = self.prefix+'-' if self.prefix else ''
            visual_acuity_method_id = self.data[prefix+'visual_acuity_method']
        else:
            visual_acuity_method_id = 'visual_acuity_method' in self.initial and self.initial['visual_acuity_method']
        if visual_acuity_method_id:
            scale_id=VisualAcuityMethod.objects.get(pk=visual_acuity_method_id).scale_id
            filtered=VisualAcuityReading.objects.filter(scale_id=scale_id)
        else:
            filtered=VisualAcuityReading.objects.none()
        for side in ['right', 'left', 'both']:
            self.fields['visual_acuity_'+side].queryset=filtered

    def clean_iop_agents(self):
        iop_agents = self.cleaned_data.get('iop_agents')
        iop_control = self.cleaned_data.get('iop_control')
        if iop_control and iop_agents == None:
            raise forms.ValidationError("IOP control agents required")
        elif not iop_control:
            return None
        return iop_agents

    def clean_visual_acuity_correction_right(self):
        visual_acuity_correction_right = self.cleaned_data.get('visual_acuity_correction_right')
        visual_acuity_right = self.cleaned_data.get('visual_acuity_right')
        if visual_acuity_right and visual_acuity_right.not_recorded:
            return None
        if not visual_acuity_correction_right:
            raise forms.ValidationError("This field is required")
        return visual_acuity_correction_right
    
    def clean_visual_acuity_correction_left(self):
        visual_acuity_correction_left = self.cleaned_data.get('visual_acuity_correction_left')
        visual_acuity_left = self.cleaned_data.get('visual_acuity_left')
        if visual_acuity_left and visual_acuity_left.not_recorded:
            return None
        if not visual_acuity_correction_left:
            raise forms.ValidationError("This field is required")
        return visual_acuity_correction_left
    
    def clean_visual_acuity_correction_both(self):
        visual_acuity_correction_both = self.cleaned_data.get('visual_acuity_correction_both')
        visual_acuity_both = self.cleaned_data.get('visual_acuity_both')
        if visual_acuity_both and visual_acuity_both.not_recorded:
            return None
        if not visual_acuity_correction_both:
            raise forms.ValidationError("This field is required")
        return visual_acuity_correction_both

PatientManagementFormSet = forms.models.inlineformset_factory(Patient, Management, form = PatientManagementForm, extra=1, can_delete=False)

PatientOutcomeFormSet = forms.models.inlineformset_factory(Patient, Outcome, form = PatientOutcomeForm, extra=1, can_delete=False)

PatientUpdateManagementFormSet = forms.models.inlineformset_factory(Patient, Management, form = PatientManagementForm, extra=1)

PatientUpdateOutcomeFormSet = forms.models.inlineformset_factory(Patient, Outcome, form = PatientOutcomeForm, extra=1)
