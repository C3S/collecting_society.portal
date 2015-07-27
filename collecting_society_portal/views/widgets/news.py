# For copyright and license terms, see COPYRIGHT.rst (top level of repository)
# Repository: https://github.com/C3S/collecting_society.portal

from pyramid.renderers import render

from ...services import _


def news_widget(request):
    heading = _(u'News')
    body = render(
        '../../templates/widgets/news.pt',
        {'news': request.context.registry['content']['news']},
        request=request
    )
    return {'heading': heading, 'body': body}
