# For copyright and license terms, see COPYRIGHT.rst (top level of repository)
# Repository: https://github.com/C3S/portal_web

"""
Helper functions for the creation of the pyramid app.
"""

import os
import logging
from pkgutil import iter_modules
import ConfigParser

from trytond.transaction import Transaction
from trytond.cache import Cache
from trytond.pool import Pool

from pyramid.httpexceptions import (
    HTTPFound,
    HTTPNotFound
)
from pyramid.renderers import get_renderer

from .models import (
    Tdb,
    WebUser
)
from . import helpers

log = logging.getLogger(__name__)


def replace_environment_vars(settings):
    """
    Substitues placeholders in app settings with environment variables.

    Values in the app settings with the syntax `${ENVIRONMENT_VARIABLE}` are
    substituted with the respective value of the key ENVIRONMENT_VARIABLE in
    the environment variables.

    Args:
        settings (dict): Parsed [app:main] section of .ini file.

    Returns:
        dict: substituted settings.

    Examples:
        >>> import os
        >>> os.environ['PYRAMID_SERVICE'] = 'portal'
        >>> settings = { 'service': '${PYRAMID_SERVICE}' }
        >>> print(replace_environment_vars(settings))
        { 'service' = 'portal' }
    """
    return dict(
        (key, os.path.expandvars(value)) for key, value in settings.iteritems()
    )


def get_plugins(settings=None):
    """
    Fetches plugin settings based on module name pattern matching.

    The module name pattern needs to be configured in the portal app settings
    as key `plugins.pattern`. All modules starting with this pattern will be
    treated as portal plugins.

    Note:
        Dots in module names get substituted by an underscore.

    Args:
        settings (dict): Parsed [app:main] section of .ini file.

    Returns:
        dict: plugin settings.

    Examples:
        >>> settings = { 'plugins.pattern': '_web' }
        >>> print(get_plugins(settings))
        {
            200: {
                'path': '/ado/src/someplugin_web',
                'name': 'someplugin_web',
                'settings': {}
            },
            100: {
                'path': '/ado/src/anotherplugin_web',
                'name': 'anotherplugin_web',
                'settings': {}
            }
        }
    """
    if not settings:
        from paste.deploy.loadwsgi import appconfig
        settings = appconfig(
            'config:' + os.path.join(
                os.path.dirname(__file__), '..',
                os.environ['ENVIRONMENT'] + '.ini'
            )
        )
    plugins = {}
    modules = [
        {'name': name, 'path': imp.path} for imp, name, _ in iter_modules()
        if name.endswith(settings['plugins.pattern']) and name != "portal_web"
    ]
    config = ConfigParser.ConfigParser()
    for plugin in modules:
        settings_path = plugin['path'] + '/' + settings['env'] + '.ini'
        config.read(settings_path)
        plugin_settings = dict(config.items('plugin:main'))
        if 'plugin.priority' not in plugin_settings:
            raise KeyError("'plugin.priority' missing in " + settings_path)
        priority = int(plugin_settings['plugin.priority'])
        del plugin_settings['plugin.priority']
        plugins[priority] = {
            'name': plugin['name'],
            'settings': plugin_settings,
            'path': plugin['path']
        }
    return plugins


def add_templates(event):
    """
    Adds base templates and macros as top-level name in temlating system.

    Args:
        event (pyramid.events.BeforeRender): BeforeRender event.

    Returns:
        None.
    """
    event.update({
        'base': get_renderer(
            'templates/base.pt').implementation(),
        'frontend': get_renderer(
            'templates/frontend.pt').implementation(),
        'backend': get_renderer(
            'templates/backend.pt').implementation(),
        'backend363': get_renderer(
            'templates/backend363.pt').implementation(),
        'backend39': get_renderer(
            'templates/backend39.pt').implementation(),
        'm': get_renderer(
            'templates/macros.pt').implementation()
    })


def add_helpers(event):
    """
    Adds helper functions as top-level name in temlating system.

    Args:
        event (pyramid.events.BeforeRender): BeforeRender event.

    Returns:
        None.
    """
    event['h'] = helpers


def add_locale(event):
    """
    Sets the language of the app.

    Considers several sources in the following, descending order:

    1. request: manual choice of language using GET parameter `_LOCALE_`
    2. cookie: formerly chosen or detected language using cookie `_LOCALE_`
    3. browser: browser language using HTTP header `Accept-Language`
    4. default: en

    The chosen or detected language will be saved in a cookie `_LOCALE_`.

    Args:
        event (pyramid.events.NewRequest): NewRequest event.

    Returns:
        None.
    """
    LANGUAGE_MAPPING = {
        'de': 'de',
        'en': 'en',
        'es': 'es',
    }
    default = 'en'

    # default locale
    current = default

    # cookie locale
    cookie = event.request.cookies.get('_LOCALE_')
    if cookie:
        event.request._LOCALE_ = cookie

    # check browser for language, if no cookie present
    browser = event.request.accept_language
    if not cookie and browser:
        match = browser.best_match(LANGUAGE_MAPPING, default)
        current = LANGUAGE_MAPPING.get(match)
        event.request._LOCALE_ = current
        event.request.response.set_cookie('_LOCALE_', value=current)

    # language request
    request = event.request.params.get('_LOCALE_')
    if request and request in LANGUAGE_MAPPING:
        current = LANGUAGE_MAPPING.get(request)
        event.request._LOCALE_ = current
        event.request.response = HTTPFound(location=event.request.path_url)
        event.request.response.set_cookie('_LOCALE_', value=current)


def open_db_connection(event):
    """ Open and close database connection """
    user = Transaction().user  # pyramid subrequests have no cursor
    cursor = Transaction().cursor and not Transaction().cursor._conn.closed
    if not user and not cursor:
        with Transaction().start(Tdb._db, 0):
            pool = Pool(str(Tdb._db))
            user = pool.get('res.user')
            context = user.get_preferences(context_only=True)
            Cache.clean(Tdb._db)
        Transaction().start(
            Tdb._db, Tdb._user, readonly=True, context=context)


def close_db_connection(event):
    """ Close database connection """
    def close_db(request):
        cursor = Transaction().cursor
        if cursor and not Transaction().cursor._conn.closed:
            Cache.resets(Tdb._db)
            Transaction().stop()
        if event.request.registry.settings['debug.tdb.transactions'] == 'true':
            Tdb.wraps = 0
    event.request.add_finished_callback(close_db)


def web_user(request):
    p = request.path
    # exclude requests
    if p.startswith('/static/') or p.startswith('/_debug_toolbar/'):
        return None
    return WebUser.current_web_user(request)


def party(request):
    p = request.path
    # exclude requests
    if p.startswith('/static/') or p.startswith('/_debug_toolbar/'):
        return None
    return WebUser.current_party(request)


def user(request):
    p = request.path
    # exclude requests
    if p.startswith('/static/') or p.startswith('/_debug_toolbar/'):
        return None
    return WebUser.current_user(request)


def roles(request):
    p = request.path
    # exclude requests
    if p.startswith('/static/') or p.startswith('/_debug_toolbar/'):
        return None
    return WebUser.current_roles(request)


def notfound(request):
    """
    Not Found view (404 Error).

    Args:
        request (pyramid.request): Current request.

    Returns:
        pyramid.httpexceptions.HTTPNotFound: 404 Response.
    """
    return HTTPNotFound()


def context_found(event):
    """Trigger _context_found() on context, after it has been found"""
    event.request.context._context_found()


def debug_context(event):
    """
    Prints context to debug log.

    Args:
        event (pyramid.events.ContextFound): ContextFound event.

    Returns:
        None.
    """
    p = event.request.path
    settings = event.request.registry.settings

    # exclude requests
    if p.startswith('/static/') or p.startswith('/_debug_toolbar/'):
        return
    # api
    if settings['service'] == 'api':
        if settings['debug.api.context'] == 'false':
            return
    # web
    if settings['service'] == 'gui':
        if settings['debug.web.context'] == 'false':
            return

    log.debug(event.request.context)


def debug_request(event):
    """
    Prints request to debug log.

    Args:
        event (pyramid.events.NewRequest): NewRequest event.

    Returns:
        None.
    """
    p = event.request.path
    settings = event.request.registry.settings

    # exclude requests
    if p.startswith('/static/') or p.startswith('/_debug_toolbar/'):
        return
    # api
    if settings['service'] == 'api':
        if settings['debug.api.request'] == 'false':
            return
    # web
    if settings['service'] == 'gui':
        if settings['debug.web.request'] == 'false':
            return
    # log
    try:
        log.debug("REQUEST:\n %s" % event.request.as_bytes(skip_body=True))
    except:  # noqa
        pass


def debug_response(event):
    """
    Prints response to debug log.

    Args:
        event (pyramid.events.NewRequest): NewRequest event.

    Returns:
        None.
    """
    p = event.request.path
    settings = event.request.registry.settings

    # exclude requests
    if p.startswith('/static/') or p.startswith('/_debug_toolbar/'):
        return
    # api
    if settings['service'] == 'api':
        if settings['debug.api.response'] == 'false':
            return
    # web
    if settings['service'] == 'gui':
        if settings['debug.web.response'] == 'false':
            return
    # log
    try:
        log.debug("RESPONSE:\n %s" % event.response.__str__(skip_body=True))
    except: # noqa
        pass


class Environment(object):
    """
    View predicate factory for restricting views to environments.

    Args:
        val (str): value for comparison.
        config (pyramid.config.Configurator): App config.

    Classattributes:
        phash (str): hash for view predicate.

    Attributes:
        val (str): value for comparison.
    """
    def __init__(self, val, config):
        self.val = val

    def text(self):
        return 'environment = %s' % (self.val,)

    phash = text

    def __call__(self, context, request):
        '''
        Compares the value of the key `env` in registry settings with the value
        of the view predicate key `environment`.

        Args:
            context (object): Current resource.
            request (pyramid.request): Current request.

        Returns:
            True if val is equal to the current environment, False otherwise.
        '''
        return request.registry.settings['env'] == self.val
