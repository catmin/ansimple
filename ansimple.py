#!/usr/bin/env python3

import json
import logging
import sys


import subprocess
import os
class AptHandler:

    provider = "package"

    def __init__(self):
        self.logger = logging.getLogger("main")
        return

    def _install(self, package):
        if os.geteuid() != 0:
            raise Exception("not effective user ID 0! run with sudo")

        cmd = [ "apt-get", "install", "-y", package ]
        self.logger.debug("running '{0}'".format(cmd))
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=1)
        self.logger.debug(process.stdout.read())
        process.communicate()
        if process.returncode != 0: raise Exception("error running process {0} - rc={1}".format(cmd[0], process.returncode))

        return

    def _is_installed(self, package):
        cmd = [ "dpkg", "-s", package ]
        self.logger.debug("running '{0}'".format(cmd))
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process.communicate()
        if process.returncode == 0: 
            return True 
        else:
            return False


    def apply(self, item):
        data = item[self.provider]
        package = data["name"]
        if not self._is_installed(package):
            self.logger.info("installing package {0}.".format(package))
            self._install(package)
        else:
            self.logger.debug("package {0} already installed.".format(package))
        return

    def __repr__(self):
        return self.provider

import os
import stat
from pwd import getpwuid, getpwnam
from grp import getgrgid, getgrnam
from string import Template
class FileHandler():
    provider = "file"

    def __init__(self):
        self.logger = logging.getLogger("main")
        return
    
    def apply(self, item):
        data = item[self.provider]
        file_path = data["path"]

        set_mode = False
        if "mode" in data:
            if isinstance(data["mode"], int):
                file_mode = data["mode"]
                # TODO check range
            #elif g+x u+s
            else:
                raise Exception("invalid mode")
            set_mode = True

        change_owner = False
        if "owner" in data: 
            # get user details by username or uid
            if isinstance(data["owner"], int):
                file_owner = getpwuid(data["owner"])
            elif isinstance(data["owner"], str):
                file_owner = getpwnam(data["owner"])
            else:
                raise Exception("invalid data type for user")
            change_owner = True

        change_group = False
        if "group" in data: 
            # get group details by groupname or gid
            if isinstance(data["group"], int):
                file_group = getpwgid(data["group"])
            elif isinstance(data["owner"], str):
                file_group = getgrnam(data["group"])
            else:
                raise Exception("invalid data type for user")
            change_group = True

        # content
        write_contents_to_file = False
        if "content" in data:
            content = data["content"]
            write_contents_to_file = True
        elif "template" in data:
            template = data["template"]
            if not os.path.exists(template): raise Exception("template '{0}' not found".format(template))
            self.logger.debug("loading template '{0}'".format(template))
            with open(template, "r") as template_file:
                template = Template(template_file.read())
                if "vars" in data:
                    template_vars = data["vars"]
                else:
                    template_vars = {}
                content = template.substitute(template_vars)
            write_contents_to_file = True
        if write_contents_to_file:
            self.logger.debug("writing to file '{0}'".format(file_path))
            with open(file_path, "w") as outfile:
                outfile.write(content)

        # the file has to exist at this stage
        if not os.path.exists(file_path): raise Exception("file '{0}' not found.".format(file_path))

        # set mode
        if set_mode:
            self.logger.debug("setting mode to {0}".format(file_mode))
            os.chmod(file_path, file_mode) # PermissionError

        # set owner and group
        if change_owner:
            self.logger.debug("setting owner of '{1}' to '{0}'".format(file_owner.pw_name, file_path))
            os.chown(file_path, file_owner.pw_uid, -1) # change only the owner
        if change_group:
            self.logger.debug("setting group of '{1}' to '{0}'".format(file_group.gr_name, file_path))
            os.chown(file_path, -1, file_group.gr_gid) # change only the group

        return

    def __repr__(self):
        return self.provider

from pwd import getpwuid, getpwnam
from grp import getgrgid, getgrnam
import crypt
class UserHandler:

    provider = "user"

    def __init__(self):
        self.logger = logging.getLogger("main")
        pass

    def crypt_password(self, clear_password):
        return crypt.crypt(clear_password, crypt.mksalt(crypt.METHOD_SHA512))

    def _create_user(self, data):
        if os.geteuid() != 0: raise Exception("not effective user ID 0! run with sudo")

        cmd = [ "useradd" ]
        cmd += [ "-m" ]
        if "shell" in data:
            cmd += [ "-s", data["shell"] ]
        if "home" in data:
            cmd += [ "-d", data["home"] ]
        if "crypt_password" in data:
            cmd += [ "-p", data["crypt_password"] ]
        elif "password" in data:
            cmd += [ "-p", self.crypt_password(data["password"]) ]
        cmd += [ data["name"]]

        self.logger.info("creating user {0}".format(data["name"]))
        self.logger.debug("cmd is {0}".format(cmd))
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=1)
        process.communicate()
        if process.returncode != 0: raise Exception("error running process {0} - rc={1}".format(cmd[0], process.returncode))

        # query the created user
        os_user = getpwnam(data["name"])

        if "ssh_authorizedkey" in data:
            self._add_sshauthorizedkey(data,  os_user.pw_dir)

        return

    def _change_user(self, data, os_user):
        if os.geteuid() != 0: raise Exception("not effective user ID 0! run with sudo")

        change_user = False
        cmd = [ "usermod" ]
        if "shell" in data and os_user.pw_shell != data["shell"]:
            cmd += [ "-s", data["shell"] ]
            change_user = True
        if "home" in data and os_user.pw_dir != data["home"]:
            cmd += [ "-d", data["home"] ]
            change_user = True
        if "crypt_password" in data:
            cmd += [ "-p", data["crypt_password"] ]
            change_user = True
        elif "password" in data:
            cmd += [ "-p", self.crypt_password(data["password"]) ]
            change_user = True
        cmd += [ data["name"] ]

        if change_user:
            self.logger.info("changing user {0}".format(data["name"]))
            self.logger.debug("cmd is {0}".format(cmd))
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=1)
            process.communicate()
            if process.returncode != 0: raise Exception("error running process {0} - rc={1}".format(cmd[0], process.returncode))
        else:
            self.logger.debug("no change of user '{0}'.".format(data["name"]))

        # create authorized key
        if "ssh_authorizedkey" in data:
            self._add_sshauthorizedkey(data,  os_user.pw_dir)

        return

    def _delete_user(self, data):
        if os.geteuid() != 0: raise Exception("not effective user ID 0! run with sudo")

        cmd = [ "userdel", data["name"] ]
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=1)
        process.communicate()
        if process.returncode != 0: raise Exception("error running process {0} - rc={1}".format(cmd[0], process.returncode))

        return

    def _add_sshauthorizedkey(self, data,  home):
        # creating .ssh directory
        ssh_dir = os.path.join(home, ".ssh")
        if not os.path.isdir(ssh_dir):
            os.mkdir(ssh_dir)
        
        # read ssh keys
        ssh_key_already_exists = False
        ssh_authorizedkey_file = os.path.join(ssh_dir, "authorized_keys")
        if os.path.isfile(ssh_authorizedkey_file):
            with open(ssh_authorizedkey_file, "r") as f:
                line = f.readline()
                while line:
                    ssh_line = line.split(" ", 3)
                    if ssh_line[1] == data["ssh_authorizedkey"]:
                        ssh_key_already_exists = True
                        break
        
        if not ssh_key_already_exists:
            # appending ssh key
            self.logger.info("adding key to .ssh/authorized_keys of user {0}".format(data["name"]))
            with open(ssh_authorizedkey_file, "a") as f:
                key_type = "ssh-rsa"
                comment = ""
                f.write(key_type + " " + str(data["ssh_authorizedkey"]) + " " + comment + "\n")
        return


    def apply(self, item):
        data = item[self.provider]
        try:
            os_user = getpwnam(data["name"])
            self._change_user(data, os_user)
        except KeyError as e:
            # user does not exist -> create it
            self._create_user(data)
        
        return


class ItemHandlerFactory:

    def __init__(self):
        self.handlers = {}
        self.add_handler(AptHandler())
        self.add_handler(FileHandler())
        self.add_handler(UserHandler())
        return

    def add_handler(self, handler):
        self.handlers[handler.provider] = handler

    def create_by_type(self, item):
        if len(item.keys()) != 1: raise Exception("malformed item {0}".format(item))
        requested_provider = list(item.keys())[0]
        if requested_provider in self.handlers.keys():
            return self.handlers[requested_provider]
        else:
            return None


def main(playbook_path):
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("main")

    # parse playbook file
    playbook = []
    with open(playbook_path, "r") as f:
        playbook = json.load(f)
    logger.debug("parsed playbook:" + str(playbook))

    # process playbook
    factory = ItemHandlerFactory()     
    for item in playbook:
        handler = factory.create_by_type(item)
        if not handler:
            raise Exception("no handler defined for '{0}'".format(list(item.keys())[0]))
            continue
        #try:
        handler.apply(item)
        #except Exception as e:
        #    logger.error("error running handler {1} with data {0}". format(item, handler))
        #    logger.error(e)
    logger.debug("done") 
    return

if __name__ == "__main__":
    if not len(sys.argv) != 1:
        print("usage: ansimple.py ./playbook.yml")
        sys.exit(1)
    playbook_path = sys.argv[1]
    if not os.path.exists(playbook_path):
        print("playbook '{0}' not found.".format(playbook_path))
        sys.exit(1)
    main(playbook_path)

