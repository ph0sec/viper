# This file is part of Viper - https://github.com/viper-framework/viper
# See the file 'LICENSE' for copying permission.

import os
from os.path import expanduser
import sys
import glob
import atexit
import readline
import traceback

from viper.common.out import print_error, print_output
from viper.common.colors import cyan, magenta, white, bold, blue
from viper.common.version import __version__
from viper.core.session import __sessions__
from viper.core.plugins import __modules__
from viper.core.project import __project__
from viper.core.ui.commands import Commands
from viper.core.database import Database
from viper.core.config import Config, console_output

cfg = Config()

# For python2 & 3 compat, a bit dirty, but it seems to be the least bad one
try:
    input = raw_input
except NameError:
    pass

def logo():
    print("""         _
        (_)
   _   _ _ ____  _____  ____
  | | | | |  _ \| ___ |/ ___)
   \ V /| | |_| | ____| |
    \_/ |_|  __/|_____)_| v{}
          |_|
    """.format(__version__))

    db = Database()
    count = db.get_sample_count()

    try:
        db.find('all')
    except:
        print_error("You need to update your Viper database. Run 'python update.py -d'")
        sys.exit()

    if __project__.name:
        name = __project__.name
    else:
        name = 'default'

    print(magenta("You have " + bold(count)) +
          magenta(" files in your " + bold(name)) +
          magenta(" repository"))

class Console(object):

    def __init__(self):
        # This will keep the main loop active as long as it's set to True.
        self.active = True
        self.cmd = Commands()

    def parse(self, data):
        root = ''
        args = []

        # Split words by white space.
        words = data.split()
        # First word is the root command.
        root = words[0]

        # If there are more words, populate the arguments list.
        if len(words) > 1:
            args = words[1:]

        return (root, args)

    def keywords(self, data):
        # Check if $self is in the user input data.
        if '$self' in data:
            # Check if there is an open session.
            if __sessions__.is_set():
                # If a session is opened, replace $self with the path to
                # the file which is currently being analyzed.
                data = data.replace('$self', __sessions__.current.file.path)
            else:
                print("No open session")
                return None

        return data

    def stop(self):
        # Stop main loop.
        self.active = False

    def start(self):
        # Logo.
        logo()

        # Setup shell auto-complete.
        def complete(text, state):
            # Try to autocomplete both commands and modules
            completions = list()
            completions += [i for i in self.cmd.commands if i.startswith(text)]
            completions += [i for i in __modules__ if i.startswith(text)]

            if state < len(completions):
                return completions[state]

            # Then autocomplete paths.
            if text.startswith("~"):
                text = "{0}{1}".format(expanduser("~"), text[1:])
            return (glob.glob(text+'*')+[None])[state]

        # Auto-complete on tabs.
        readline.set_completer_delims(' \t\n;')
        readline.parse_and_bind('tab: complete')
        readline.set_completer(complete)

        # Save commands in history file.
        def save_history(path):
            readline.write_history_file(path)

        # If there is an history file, read from it and load the history
        # so that they can be loaded in the shell.
        # Now we are storing the history file in the local project folder
        history_path = os.path.join(__project__.path, 'history')

        if os.path.exists(history_path):
            readline.read_history_file(history_path)

        # Register the save history at program's exit.
        atexit.register(save_history, path=history_path)

        # Main loop.
        while self.active:
            # If there is an open session, we include the path to the opened
            # file in the shell prompt.
            # TODO: perhaps this block should be moved into the session so that
            # the generation of the prompt is done only when the session's
            # status changes.
            prefix = ''
            if __project__.name:
                prefix = bold(cyan(__project__.name)) + ' '

            if __sessions__.is_set():
                stored = ''
                filename = ''
                if __sessions__.current.file:
                    filename = __sessions__.current.file.name
                    if not Database().find(key='sha256', value=__sessions__.current.file.sha256):
                        stored = magenta(' [not stored]', True)

                misp = ''
                if __sessions__.current.misp_event:
                    misp = '[MISP'
                    if __sessions__.current.misp_event.event.id:
                        misp += ' {}'.format(__sessions__.current.misp_event.event.id)
                    else:
                        misp += ' New Event'
                    if __sessions__.current.misp_event.off:
                        misp += ' (Offline)'
                    misp += ']'

                prompt = (prefix + cyan('viper ', True) +
                          white(filename, True) + blue(misp, True) + stored + cyan(' > ', True))
            # Otherwise display the basic prompt.
            else:
                prompt = prefix + cyan('viper > ', True)

            # Wait for input from the user.
            try:
                data = input(prompt).strip()
            except KeyboardInterrupt:
                print("")
            # Terminate on EOF.
            except EOFError:
                self.stop()
                print("")
                continue
            # Parse the input if the user provided any.
            else:
                # If there are recognized keywords, we replace them with
                # their respective value.
                data = self.keywords(data)
                # Skip if the input is empty.
                if not data:
                    continue

                # Check for output redirection
                # If there is a > in the string, we assume the user wants to output to file.
                if '>' in data:
                    data, console_output['filename'] = data.split('>')
                    print("Writing output to {0}".format(console_output['filename'].strip()))


                # If the input starts with an exclamation mark, we treat the
                # input as a bash command and execute it.
                # At this point the keywords should be replaced.
                if data.startswith('!'):
                    os.system(data[1:])
                    continue

                # Try to split commands by ; so that you can sequence multiple
                # commands at once.
                # For example:
                # viper > find name *.pdf; open --last 1; pdf id
                # This will automatically search for all PDF files, open the first entry
                # and run the pdf module against it.
                split_commands = data.split(';')
                for split_command in split_commands:
                    split_command = split_command.strip()
                    if not split_command:
                        continue

                    # If it's an internal command, we parse the input and split it
                    # between root command and arguments.
                    root, args = self.parse(split_command)

                    # Check if the command instructs to terminate.
                    if root in ('exit', 'quit'):
                        self.stop()
                        continue

                    try:
                        # If the root command is part of the embedded commands list we
                        # execute it.
                        if root in self.cmd.commands:
                            self.cmd.commands[root]['obj'](*args)
                            del(self.cmd.output[:])
                        # If the root command is part of loaded modules, we initialize
                        # the module and execute it.
                        elif root in __modules__:
                            module = __modules__[root]['obj']()
                            module.set_commandline(args)
                            module.run()

                            if cfg.modules.store_output and __sessions__.is_set():
                                try:
                                    Database().add_analysis(__sessions__.current.file.sha256, split_command, module.output)
                                except:
                                    pass
                            del(module.output[:])
                        else:
                            print("Command not recognized.")
                    except KeyboardInterrupt:
                        pass
                    except Exception:
                        print_error("The command {0} raised an exception:".format(bold(root)))
                        traceback.print_exc()

                console_output['filename'] = None   # reset output to stdout
