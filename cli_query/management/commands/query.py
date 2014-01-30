# Copyright (c) 2009-2014 Dennis Kaarsemaker <dennis@kaarsemaker.net>
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
from django.db.models.base import ModelBase
from django.db.models.fields import FieldDoesNotExist
from django.core.exceptions import FieldError
from django.core.management import BaseCommand, CommandError
from django.template import loader, Template, Context, TemplateSyntaxError, TemplateDoesNotExist
from django.conf import settings
from optparse import make_option
import os.path
import sys

usage="""The django ORM will be queried with the filters on the commandline. Records
will be separated with newlines, fields with the specified separator
(the default is a comma). Alternatively, a template can be specified which
will be passed the result of the query as the 'objects' variable.

Query key/value pairs can be prefixed with a '!' or '~' to negate the query.
The __in filter works, use a comma separated string of arguments

You can also update fields using -u field=value. For every changed object, you
will be prompted to approve the changes.

Examples:
 - Display name and assettag of all mc01 servers
   %prog query -a servers -m Server name__startswith=mc01 -f name,assettag
 - Get a list of name, ip, mac for all servers where the does not contain .82.
   %prog query -a servers -m Interface !ip_address__contains='.82.' -f server.name,ip_address,mac_address
 - Use a template to get the roles, depending on mac address
   %prog query -a servers -m Server interface__mac_address=00:17:A4:8D:E6:BC -t '{{ objects.0.role_set.all|join:"," }}'
 - List all eth0/eth1 network interfaces
   %prog query -a servers -m Interface name__in=eth0,eth1 -f ip_address,mac_address
 - Update the state of all mc2* servers
   $prog query -a servers -m Server name__startswith=mc2 -u status=live

Operators you can filter with are listed on
https://docs.djangoproject.com/en/dev/ref/models/querysets/#field-lookups"""

class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('-a', '--application', dest="application", default=None,
                    help="Use this application", metavar="APP"),
        make_option('-m', '--model', dest="model", default=None,
                    help="Query this model"),
        make_option('-f', '--fields', dest="fields", default=None,
                    help="Give these fields"),
        make_option('-l', '--list-fields', dest="list_fields", default=False, action="store_true",
                    help="List all available fields instead of running a query"),
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
            raise CommandError("You must specify which application to use")
        if not options['model']:
            raise CommandError("You must specify which model to use")
        if not options['fields'] and not options['template'] and not options['template_file'] and not options['updates']:
            raise CommandError("You must specify a list of fields, a template or a set of updates")

        # Import the model
        models = '%s.models' % options['application']
        if options['application'] not in settings.INSTALLED_APPS:
            raise CommandError("Application %s not found in INSTALLED_APPS. All applications: \n - %s" %
                    (options['application'], "\n - ".join(settings.INSTALLED_APPS)))
        try:
            __import__(models)
        except ImportError:
            raise CommandError("Application %s could not be imported" % options['application'])
        models = sys.modules[models]
        models_ = sorted([x for x in models.__dict__ if isinstance(models.__dict__[x], ModelBase)])
        if options['model'] not in models_:
            raise CommandError("Application %s has no %s model. Available models: \n - %s" %
                    (options['application'], options['model'], "\n - ".join(models_)))
        model = getattr(models, options['model'])

        # Help the user by displaying all fields if requested
        if options['list_fields']:
            self.stdout.write("Fields for %s.models.%s:\n - %s" % (options['application'], options['model'], '\n - '.join(model._meta.get_all_field_names())))
            return

        # Create queryset from commandline arguments
        qargs = make_filter(args)
        try:
            queryset = model.objects.filter(*qargs).distinct()
        except FieldError:
            e = sys.exc_info()[1]
            raise CommandError(str(e))
        if options['order']:
            queryset = queryset.order_by(options['order'])

        # Update
        if options['updates']:
            for update in options['updates']:
                if '=' not in update:
                    raise CommandError("Invalid update statement: %s" % update)
            updates = dict([x.split('=', 1) for x in options['updates']])

            for key in updates:
                valid_fields = [x[0].name for x in model._meta.get_fields_with_model()]
                try:
                    field = model._meta.get_field_by_name(key)[0]
                    if key not in valid_fields:
                        raise FieldDoesNotExist("Field %s is not a direct field." % key)
                    choices = [x[0] for x in model._meta.get_field_by_name(key)[0].choices]
                except FieldDoesNotExist:
                    e = "%s. Choices are: %s" % (str(sys.exc_info()[1]), ', '.join(valid_fields))
                    raise CommandError(e)
                if choices and updates[key] not in choices:
                    raise ValueError("Invalid choice for %s: %s. Valid choices: %s" % (key, updates[key], ', '.join(choices)))
            keylen = max([len(x) for x in updates]) + 3
            vallen = max([len(str(getattr(obj, key))) for obj in queryset for key in updates]) + 3
            for obj in queryset:
                self.stdout.write(str(obj))
                for key in sorted(updates.keys()):
                    sys.stdout.write('  ' +  key + ' ' * (keylen - len(key)))
                    sys.stdout.write(str(getattr(obj, key)) + ' ' * (vallen - len(str(getattr(obj,key)))))
                    sys.stdout.write('=> ' + updates[key] + "\n")
            resp = raw_input("Apply changes? [y/N] ")
            if resp.lower() != 'y':
                self.stdout.write("Aborted")
            else:
                queryset.update(**updates)
                self.stdout.write("Applied!")

        # Generate output
        if options['template']:
            try:
                template = Template(options['template'])
            except TemplateSyntaxError:
                raise CommandError("Syntax error in template: %s" % str(sys.exc_info()[1]))
            self.stdout.write(template.render(Context({'objects': queryset})))
        if options['template_file']:
            tf = options['template_file']
            if tf == '-':
                template = Template(sys.stdin.read())
            elif tf and os.path.exists(tf):
                try:
                    template = Template(open(tf).read())
                except TemplateSyntaxError:
                    raise CommandError("Syntax error in template: %s" % str(sys.exc_info()[1]))
            elif tf:
                try:
                    template = loader.get_template(tf)
                except TemplateDoesNotExist:
                    raise CommandError("Cannot find a template named %s" % tf)
                except TemplateSyntaxError:
                    raise CommandError("Syntax error in template: %s" % str(sys.exc_info()[1]))
            self.stdout.write(template.render(Context({'objects': queryset})))
        elif options['fields']:
            def getattr_r(obj, attr):
                if '.' in attr:
                    me, next = attr.split('.',1)
                    try:
                        return getattr_r(getattr(obj, me), next)
                    except AttributeError:
                        e = "%s. Choices are: %s" % (str(sys.exc_info()[1]), ', '.join(sorted([x for x in dir(obj) if not x.startswith('_')])))
                        raise CommandError(e)
                try:
                    return getattr(obj, attr)
                except AttributeError:
                    e = "%s. Choices are: %s" % (str(sys.exc_info()[1]), ', '.join(sorted([x for x in dir(obj) if not x.startswith('_')])))
                    raise CommandError(str(e))

            fields = options['fields'].split(',')
            for record in queryset:
                self.stdout.write(options['separator'].join([unicode(getattr_r(record, x)) for x in fields]))

def make_filter(args):
    qargs = []
    for x in args:
        if not x:
            continue
        if '=' not in x:
            raise CommandError("Invalid filter: %s" % x)
        key, val = x.split('=',1)
        if key.endswith('__in'):
            val = val.split(',')
        if key.startswith('!') or key.startswith('~'):
            qargs.append(~Q(**{key[1:]: val}))
        else:
            qargs.append(Q(**{key: val}))
    return qargs
