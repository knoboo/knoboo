##################################################################### 
# Copyright (C) 2009 Alex Clemesha <clemesha@gmail.com>
#                and Dorian Raymer <deldotdr@gmail.com>
# 
#  Distributed under the terms of the GNU General Public License (GPL)
#                  http://www.gnu.org/licenses/
##################################################################### 
"""
Knoboo web and kernel services.

"""

import os

from zope.interface import implements

from twisted.web import server, resource, wsgi, static
from twisted.cred import portal, checkers, credentials
from twisted.spread import pb
from twisted.internet import reactor, defer
from twisted.application import internet, service
from twisted.python import usage

from knoboo.kernel.server import KernelManagerRealm
from knoboo.kernel.procman import ProcessManager
from knoboo.kernel.process import KernelProcessControl
from knoboo.async.webresources import Notebook
from knoboo.async.webresources import SessionManager
from knoboo.async.webresources import AppEngineSessionManager

os.environ['DJANGO_SETTINGS_MODULE'] = 'knoboo.settings'

from knoboo import settings

VERSION = '0.2'
KERNEL_VERSION = '0.2'

class DesktopOptions(usage.Options):
    """Main command line options for the desktop server.
     - host name
     - port number
     - proxy configuration
     - secure, use ssl

    """

    optParameters = [
            ['host', 'h', settings.APP_HOST, 'Host address to listen on'],
            ['port', 'p', settings.APP_PORT, 'Port number to listen on'],
            ['kernel_host', 'k', settings.KERNEL_HOST, 'kernel Server host'],
            ['kernel_port', 'q', settings.KERNEL_PORT, 'Kernel Server port'],
            ['env_path', 'e', os.path.join(os.getenv('HOME'), '.knoboo', 'knoboo'), 
                'Path containing config, tac, and db'],
        ]

    optFlags = [
            ['devel_mode', 'd', 'Development mode'],
            ['open_browser', 'b', 'Automatically open web browser']
        ]


    def opt_version(self):
        print 'Knoboo Desktop version: %s' % VERSION
        sys.exit(0)

class WebAppOptions(usage.Options):
    """Main command line options for the app server.
     - host name
     - port number
     - proxy configuration
     - secure, use ssl

    """

    optParameters = [
            ['host', 'h', settings.APP_HOST, 'Host address to listen on'],
            ['port', 'p', settings.APP_PORT, 'Port number to listen on'],
            ['kernel_host', 'k', settings.KERNEL_HOST, 'kernel Server host'],
            ['kernel_port', 'q', settings.KERNEL_PORT, 'Kernel Server port'],
            ['kernel_service', None, settings.KERNEL_SERVICE, 'Provider of notebook kernel service'],
            ['static_path', None, None, 'Static path for web server'],
            ['url_root', 'u', '/', 'Root url path for web server'],
            ['url_static_root', 's', '/', 'Static root url path for web server'],
            ['env_path', 'e', os.path.join(os.getenv('HOME'), '.knoboo', 'knoboo'), 
                'Path containing config, tac, and db'],
        ]

    optFlags = [
            ['proxy', 'r', 'Use in reverse proxy configuration'],
            ['devel_mode', 'd', 'Development mode'],
        ]


    def opt_version(self):
        print 'Knoboo WebApp version: %s' % VERSION
        sys.exit(0)


class KernelServerOptions(usage.Options):
    """Options for the kernel server
    """
    dconfig = {'python':'/usr/bin/python'}

    optParameters = [
            ['host', 'h', settings.KERNEL_HOST, 'Interface to listen on'],
            ['port', 'p', settings.KERNEL_PORT, 'Port number to listen on'],
            ['env_path', 'e', os.path.join(os.getenv('HOME'), '.knoboo', 'kernel'), 
                'Path containing config, tac, and db'],
            ['engines-path', None, settings.ENGINES_PATH, 'run-path for engine processes'],
            ['engines-root', None, None, 
                'root path for chroot of engine process'],
            ['engines-pythonpath', None, None, 'Packages in chroot jail'],
            ['engines-uid', 'u', None, 
                'uid of engine processes. Overriden if max-engines > 1'],
            ['engines-gid', 'g', None, 'gid of engine processes'],
            ['engines-max', 'm', 1, 
                'Maximum number of simultaneous engine processes'],
        ]

    optFlags = [
            ['secure', 's', 'NOT IMPLEMENTED! Use HTTPS SSL'],
        ] 



    def opt_version(self):
        print 'Knoboo Kernel version: %s' % KERNEL_VERSION
        sys.exit(0)



def webResourceFactory(nbSessionManager):
    """This factory function creates an instance of the front end web
    resource tree containing both the django wsgi and the async
    notebook resources.
    """

    class Root(resource.Resource):

        def __init__(self, wsgi_resource):
            resource.Resource.__init__(self)
            self.wsgi_resource = wsgi_resource

        def getChild(self, path, request):
            path0 = request.prepath.pop(0)
            request.postpath.insert(0, path0)
            return self.wsgi_resource


    # The kernel server does not require django, so this step is not
    # required for every import of service.py (this file)
    from django.core.handlers.wsgi import WSGIHandler
    from twisted.python import threadpool

    pool = threadpool.ThreadPool()
    pool.start()
    reactor.addSystemEventTrigger('after', 'shutdown', pool.stop)

    django_wsgi_resource = wsgi.WSGIResource(reactor, pool, WSGIHandler())
    resource_root = Root(django_wsgi_resource)

    #nbSessionManager = SessionManager() #XXX improve
    notebook_resource = Notebook(nbSessionManager)
    static_resource = static.File(os.path.abspath(".")+"/knoboo/static")

    resource_root.putChild("asyncnotebook", notebook_resource)
    resource_root.putChild("static", static_resource)

    return resource_root


class DesktopServiceMaker(object):

    implements(service.IServiceMaker, service.IPlugin)
    tapname = "knoboo"
    description = ""
    options = DesktopOptions

    def makeService(self, options):
        """
        Return a service collection of two services.
        The web resource tree contains the wsgi interface to django and 
        the async notebook web resources.

        The process manager service will start the kernel server. 
        The kernel server process is another twistd plugin, and needs a 
        few options passed to it.  
        """
        desktop_service = service.MultiService()

        nbSessionManager = SessionManager(options)
        web_resource = webResourceFactory(nbSessionManager)
        web_resource_factory = server.Site(web_resource)

        tcp_server = internet.TCPServer(options['port'],
                                    web_resource_factory,
                                    interface='localhost')
        tcp_server.setServiceParent(desktop_service)


        ##########################
        #XXX Hack Time. Fix This!!
        #
        class Config(object):
            kernel = {}
            database = {}
            server = {}

        kernel_config = Config()
        kernel_config.kernel["kernel_path"] = os.path.abspath(".")
        kernel_config.kernel["kernel_host"] = "localhost"
        kernel_config.kernel["kernel_port"] = 8337

        kernel_process_control = KernelProcessControl(kernel_config)
        kernel_process_control.buildProcess()
        #
        ##########################

        procman = ProcessManager()
        procman.addProcess(kernel_process_control)
        procman.setServiceParent(desktop_service)

        return desktop_service


class WebAppServiceMaker(object):

    implements(service.IServiceMaker, service.IPlugin)
    tapname = "knobood"
    description = ""
    options = WebAppOptions

    def makeService(self, options):
        """
        This service is like the desktop, but is not responsible for
        controlling the kernel server process.
        """

        web_app_service = service.MultiService()

        if options['kernel_service'] == 'appengine':
            nbSessionManager = AppEngineSessionManager(options)
        else:
            nbSessionManager = SessionManager(options)

        web_resource = webResourceFactory(nbSessionManager)
        web_resource_factory = server.Site(web_resource)

        tcp_server = internet.TCPServer(options['port'], 
                                    web_resource_factory, 
                                    interface=options['host'])
        tcp_server.setServiceParent(web_app_service)
        return web_app_service



class KernelServerServiceMaker(object):

    implements(service.IServiceMaker, service.IPlugin)
    tapname = "knoboo-kernel"
    description = ""
    options = KernelServerOptions

    def makeService(self, options):
        """
        """
        kernel_service = service.MultiService()

        procman = ProcessManager()
        procman.setServiceParent(kernel_service)
        
        ########################################
        #XXX Hack left over
        engines_max = 0 #int(config['engines-max'])
        if engines_max > 1:
            from knoboo.kernel.interface import UserPool
            prefix = config['engines-user-prefix']
            group = config['engines-group']
            user_pool = UserPool(engines_max, prefix, group)
        else:
            user_pool = None

        class InMemoryPasswordDatabase(checkers.InMemoryUsernamePasswordDatabaseDontUse):
            """This is used for authenticating kernel connections.
            It is a temporary solution that needs a little more... 
            """

            def requestAvatarId(self, credentials):
                return defer.maybeDeferred(
                        credentials.checkPassword, 
                        self.users['user1']).addCallback(
                        self._cbPasswordMatch, str(credentials.username))


        realm = KernelManagerRealm(options, procman, user_pool)
        p = portal.Portal(realm)
        chk = InMemoryPasswordDatabase(user1="secret")
        p.registerChecker(chk)

        kernel_server = internet.TCPServer(options['port'], 
                    pb.PBServerFactory(p),
                    interface=options['host'])
        kernel_server.setServiceParent(kernel_service)

        return kernel_service




