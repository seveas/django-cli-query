# Copyright (c) 2009-2012 Dennis Kaarsemaker <dennis@kaarsemaker.net>
# A command-line interface to query the Django ORM
# 
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
# 
#     1. Redistributions of source code must retain the above copyright notice, 
#        this list of conditions and the following disclaimer.
#     
#     2. Redistributions in binary form must reproduce the above copyright 
#        notice, this list of conditions and the following disclaimer in the
#        documentation and/or other materials provided with the distribution.
# 
#     3. Neither the name of Django nor the names of its contributors may be used
#        to endorse or promote products derived from this software without
#        specific prior written permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from django.db.models import Q
from django.core.management import BaseCommand
from django.template import loader, Template, Context
from django.conf import settings
from optparse import make_option
import os.path
import sys

usage="""The django ORM will be queried with the filters on the commandline. Records
will be separated with newlines, fields with the specified separator 
(the default is a comma). Alternatively, a template can be specified which 
will be passed the result of the query as the 'objects' variable

Query key/value pairs can be prefixed with a '!' or '~' to negate the query.
The __in filter works, use a comma separated string of arguments

Examples:
 - Display name and assettag of all mc01 servers
   %prog query -a servers -m Server name__startswith=mc01 -f name,assettag
 - Get a list of name, ip, mac for all servers where the does not contain .82.
   %prog query -a servers -m Interface !ip_address__contains='.82.' -f server.name,ip_address,mac_address
 - Use a template to get the roles, depending on mac address
   %prog query -a servers -m Server interface__mac_address=00:17:A4:8D:E6:BC -t '{{ objects.0.role_set.all|join:"," }}'
 - List all eth0/eth1 network interfaces
   %prog query -a servers -m Interface name__in=eth0,eth1 -f ip_address,mac_address

/!\\ Warning /!\\
This script does not do much error checking. If you spell your query wrong, or
do something wrong with templates, you will get a python traceback and not a
nice error message."""

class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('-a', '--application', dest="application", default=None,
                    help="Use this application", metavar="APP"),
        make_option('-m', '--model', dest="model", default=None,
                    help="Query this model"),
        make_option('-f', '--fields', dest="fields", default=None,
                    help="Give these fields"),
        make_option('-o', '--order', dest="order", default=None,
                    help="Order by this field"),
        make_option('-s', '--separator', dest="separator", default=",",
                    help="Output separator"),
        make_option('-t', '--template', dest="template", default='',
                    help="Template in django syntax"),
        make_option('-T', '--template-file', dest="template_file", default=None,
                    help="File containing the template (abs/rel path or loader path)"),
        make_option('-u', '--update', dest="updates", default=[], action="append",
                    help="Updates to apply"),
    )
    help = usage
    args = 'filter [filter ...]'

    def handle(self, *args, **options):
        if not options['application']:
            print "You must specify which application to use"
            sys.exit(1)
        if not options['model']:
            print "You must specify which model to use"
            sys.exit(1)
        if not options['fields'] and not options['template'] and not options['template_file'] and not options['updates']:
            print "You must specify a list of fields, a template or a set of updates"
            sys.exit(1)

        # Import the model
        project_name = settings.SETTINGS_MODULE.split('.')[-2]
        models = '.'.join([project_name, options['application'], 'models'])
        __import__(models)
        models = sys.modules[models]
        model = getattr(models, options['model'])

        # Create queryset from commandline arguments
        qargs = []
        for x in args:
            key, val = x.split('=',1)
            if key.endswith('__in'):
                val = val.split(',')
            if key.startswith('!') or key.startswith('~'):
                qargs.append(~Q(**{key[1:]: val}))
            else:
                qargs.append(Q(**{key: val}))
        queryset = model.objects.filter(*qargs).distinct()
        if options['order']:
            queryset = queryset.order_by(options['order'])

        # Update
        if options['updates']:
            updates = dict([x.split('=', 1) for x in options['updates']])
            for key in updates:
                choices = [x[0] for x in model._meta.get_field_by_name(key)[0].choices]
                if choices and updates[key] not in choices:
                    raise ValueError("Invalid choice for %s: %s. Valid choices: %s" % (key, updates[key], ', '.join(choices)))
            keylen = max([len(x) for x in updates]) + 3
            vallen = max([len(getattr(obj, key)) for obj in queryset for key in updates]) + 3
            for obj in queryset:
                print str(obj)
                for key in sorted(updates.keys()):
                    sys.stdout.write('  ' +  key + ' ' * (keylen - len(key)))
                    sys.stdout.write(getattr(obj, key) + ' ' * (vallen - len(getattr(obj,key))))
                    sys.stdout.write('=> ' + updates[key] + "\n")
            resp = raw_input("Apply changes? [y/N] ")
            if resp.lower() != 'y':
                print "Aborted"
            else:
                queryset.update(**updates)
                print "Applied!"

        # Generate output
        if options['template'] or options['template_file']:
            template = Template(options['template'])
            tf = options['template_file']
            if tf == '-':
                template = Template(sys.stdin.read())
            elif tf and os.path.exists(tf):
                template = Template(open(tf).read())
            elif tf:
                template = loader.get_template(tf)
            print template.render(Context({'objects': queryset}))
        elif options['fields']:
            def getattr_r(obj, attr):
                if '.' in attr:
                    me, next = attr.split('.',1)
                    return getattr_r(getattr(obj, me), next)
                return getattr(obj, attr)
            fields = options['fields'].split(',')
            for record in queryset:
                print options['separator'].join([unicode(getattr_r(record, x)) for x in fields])
