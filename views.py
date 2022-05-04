from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from .models import Question, Answer, ContextQuestionnaire
from .forms import QuestionnaireForm
from django.db.models import Count


@login_required
@never_cache
def questionnaire(request):
    """
        Construct a questionnaire block and render question groups on different pages
        2 possible outcomes:
        1- Render the correct questionnaire according to participant.extra_json.questions_extra
        2- Delete participant extra_json.questions_extra and leave questionnaire
    """
    participant = request.user.participantprofile
    if 'questions_extra' not in participant.extra_json:
        build_participant_question_extra(participant)
    questions_extra = participant.extra_json['questions_extra']
    groups = questions_extra['grouped_handles']
    ind = questions_extra['ind']
    questions = Question.objects.filter(handle__in=groups[ind]).order_by('order')
    form = QuestionnaireForm(questions, request.POST or None)
    if form.is_valid():
        save_answer(questions, participant, form)
        participant.extra_json['questions_extra']['ind'] += 1
        participant.save()
        if participant.extra_json['questions_extra']['ind'] == len(groups):
            del participant.extra_json['questions_extra']
            participant.save()
            return redirect(reverse('end_task'))
        return redirect(reverse(questionnaire))
    return render(request, 'question_block.html', {'CONTEXT': {
        'form': form,
        'current_page': groups.index(groups[ind]) + 1,
        'nb_pages': len(groups),
        'side_pannel': participant.extra_json['questions_extra']['context']
    }})


def build_participant_question_extra(participant):
    """
        Survey_app use extra_json field of the participant to store groups of questions and current indice of page
        If the participant starts a questionnaire, the question_extra field is built in the extra_json through this
        utility function.
    """
    # From the current task, retrieve questions and excluded ones:
    task_extra = participant.current_task.extra_json
    questions = Question.objects.filter(instrument__in=task_extra['instruments'])
    for k, v in task_extra.setdefault('exclude', {}).items():
        questions = questions.exclude(**{k: v})
    # Then create dict representing groups of questions and retrieve nb of questions per grps:
    groups = [i for i in questions.values('instrument', 'group').annotate(size=Count('handle'))]
    # Then sort all groups from order value
    order = {k: v for v, k in enumerate(task_extra['instruments'])}
    for d in groups:
        d['order'] = order[d['instrument']]
    groups = sorted(groups, key=lambda d: (d['order'], d['group']))
    # Finally retrieve handles for each questions per group
    grouped_handles = []
    for group in groups:
        grouped_handles.append(
            tuple(questions.filter(
                instrument__exact=group['instrument'],
                group__exact=group['group']
            ).order_by('order').values_list('handle', flat=True))
        )
    participant.extra_json['questions_extra'] = {'grouped_handles': grouped_handles}
    participant.extra_json['questions_extra']['ind'] = 0
    # Finally, for this questionnaire look for a specific context:
    participant.extra_json['questions_extra']['context'] = {}
    if "context__handle" in task_extra:
        context = ContextQuestionnaire.objects.filter(handle=task_extra['context__handle']).distinct()
        if context.exists():
            participant.extra_json['questions_extra']['context'] = {'context__handle': task_extra['context__handle'],
                                                                    'context__prompt': format_prompt(context[0].prompt)}
    participant.save()


def save_answer(questions, participant, form):
    """
        Utility function to store an answer if the form is valid
    """
    for q in questions:
        if q.widget != 'custom-header':
            answer = Answer()
            if participant.extra_json['questions_extra']['context']:
                context_handle = participant.extra_json['questions_extra']['context']['context__handle']
                answer.contextQ = ContextQuestionnaire.objects.filter(handle=context_handle).distinct()[0]
            answer.participant = participant
            answer.session = participant.current_session
            answer.study = participant.study
            answer.question = q
            answer.value = form.cleaned_data[q.handle]
            answer.save()


def format_prompt(prompt):
    """
        Prompt are stored like that title1=text~title2=text2
        This function parse this format into a dict like that {title1: text, title2: text}
    """
    blocs = prompt.split('~')
    prompt_dict = {}
    for bloc in blocs:
        split_bloc = bloc.split('=')
        prompt_dict[split_bloc[0]] = split_bloc[-1]
    return prompt_dict