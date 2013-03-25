#!/usr/bin/env python

from ros_gbp_ordering import package_build_order, VcsPackagesCache
from vcstools.common import run_shell_command
from vcstools.git import GitClient
from vcstools.vcs_base import VcsError
import apt
import os.path
import shutil

import rospkg.distro
from buildfarm.rosdistro import Rosdistro, debianize_package_name

import glob
import argparse

def parse_options():
  parser = argparse.ArgumentParser(description = 'Builds and installs Debian packages for ROS git-buildpackage packages.')
  parser.add_argument('--workspace', dest='workspace', default='./tmp_workspace',
      help='Directory for building packages within.  Repositories will be checked out into this directory.')
  parser.add_argument(dest='packages', nargs='+',
      help='List of ROS packages to install')
  args = parser.parse_args()
  return args


class RosGitBuildError(Exception):
  """Thrown when the git-build-package process fails in some way."""

  def __init__(self, value):
    super(RosGitBuildError, self).__init__(self)
    self.value = value

  def __str__(self):
    return repr(self.value)


class VcsPackageFetcher(object):
  def __init__(self, rd_obj, workspace):
    if not os.path.exists(workspace):
      os.makedirs(workspace)
    self.workspace = workspace
    self._rosdist = rd_obj

  def url(self, package_name):
    pkg_info = self._rosdist.get_package_checkout_info()[package_name]
    return pkg_info['url']

  def checkout_package(self, package_name):
    """Fetches and checks out the correct version of a package for the rosdistro"""
    pkg_info = self._rosdist.get_package_checkout_info()[package_name]
    repo_url = pkg_info['url']
    name = os.path.basename(pkg_info['url'])
    repo_path = os.path.join(self.workspace, name)
    client = GitClient(repo_path)
    tag = client.is_tag(pkg_info['version']) ? pkg_info['version'] : pkg_info['full_version']
    if client.path_exists():
      if client.get_url() == repo_url:
        updated = client.update(tag, force_fetch=True, verbose=True)
      if not updated:
        print("WARNING: Repo at %s changed url from %s to %s or update failed. Redownloading!" % (repo_path, client.get_url(), repo_url))
        shutil.rmtree(repo_path)
        checkedout = client.checkout(pkg_info['url'], refname=None, shallow=False, verbose=True)
        client._do_fetch()
        tag = client.is_tag(pkg_info['version'], fetch=False) ? pkg_info['version'] : pkg_info['full_version']
        cilient.update(tag, force_fetch=False, verbose=True)
        if not checkedout:
          print("ERROR: Repo at %s could not be checked out from %s with version %s!" % (repo_path, repo_url, pkg_info['version']))

    else:
      checkedout = client.checkout(pkg_info['url'], pkg_info['version'], shallow=False, verbose=True)
      if not checkedout:
        print("ERROR: Repo at %s could not be checked out from %s with version %s!" % (repo_path, repo_url, pkg_info['version']))

    return repo_path


def install_debian_build_dependencies(package_dir):
  (returncode, result, message) = run_shell_command('dpkg-checkbuilddeps', package_dir, shell=True, show_stdout=True)
  if returncode != 0:
    missing_deps = message.split(':')[-1].split(' ')
    # things with parens are versions, ignore them
    missing_deps = [x.strip() for x in missing_deps if x != '' and (not (x.startswith('(') or x.endswith(')')))]
    print ("Warning: Attempting to install missing build-deps: %s" % missing_deps)
    (returncode, result, message) = run_shell_command('sudo apt-get -y install %s' % ' '.join(missing_deps), package_dir, shell=True, show_stdout=True)
    return returncode == 0
  else:
    return True

def build_debian_package(package_fetcher, package_name, apt_cache, rd_obj, levels=0, get_dependencies=False):
  level_prefix = '--' * levels
  print("%s> Building package %s" % (level_prefix, package_name))
  deb_package_name = debianize_package_name('groovy', package_name)
  deb_package_version = rd_obj.get_version(package_name, full_version=True) + 'quantal'
  print("%s--> Checking if installed (%s, %s).." % (level_prefix, deb_package_name, deb_package_version)),
  if deb_package_name in apt_cache and apt_cache[deb_package_name].installed.version == deb_package_version:
    print("OK")
    print("%s is installed already - remove the package if you want to re-install." % (package_name))
    return True
  print("missing!")
  if get_dependencies:
    dependencies = package_build_order([package_name], package_fetcher.workspace, distro_name='groovy', package_cache=VcsPackagesCache())
    print("%s--> Checking Dependencies:" % (level_prefix))
    for dep_pkg_name in dependencies:
      if dep_pkg_name != package_name:
        print("%s---- %s....." % (level_prefix, dep_pkg_name)),
        debian_pkg_name = debianize_package_name('groovy', dep_pkg_name)
        if debian_pkg_name in apt_cache and apt_cache[debian_pkg_name].installed is not None:
          print(" OK! (installed version %s)" % apt_cache[debian_pkg_name].installed.version)
        else:
          print(" Needs build, building...")
          build_debian_package(package_fetcher, dep_pkg_name, apt_cache, rd_obj, levels + 1)
    print("%s<<-- Dependencies OKAY." % (level_prefix))
  print("%s>>> Build debian package %s from repo %s" % (level_prefix, deb_package_name, package_fetcher.url(package_name)))
  repo_path = package_fetcher.checkout_package(package_name)
  client = GitClient(repo_path)
  deb_package_tag = deb_package_name + '_' + rd_obj.get_version(package_name, full_version=True) + '_quantal'
  bloom_package_version = 'debian/' + deb_package_tag
  client.update(bloom_package_version)
  installed_builddeps = install_debian_build_dependencies(repo_path)
  if not installed_builddeps:
    raise RosGitBuildError("%s!!! Error building %s from %s: Can't install build-dependencies!" % (level_prefix, deb_package_name, package_fetcher.url(package_name)))
  (returncode, result, message) = run_shell_command('debuild clean', repo_path, shell=True, show_stdout=True)
  if returncode != 0:
    raise RosGitBuildError("%s!!! Error building %s from %s: %s \n %s" % (level_prefix, deb_package_name, package_fetcher.url(package_name), 'debuild clean', message))
  (returncode, result, message) = run_shell_command('debuild binary', repo_path, shell=True, show_stdout=True)
  if returncode != 0:
    raise RosGitBuildError("%s!!! Error building %s from %s: %s \n %s" % (level_prefix, deb_package_name, package_fetcher.url(package_name), 'debuild binary', message))
  deb_files = glob.glob(os.path.join(repo_path, '..', '%s*.deb' % (deb_package_name + '_' + rd_obj.get_version(package_name, full_version=True))))
  if len(deb_files) > 0:
    # install the deb
    from apt.debfile import DebPackage
    deb_pkg = DebPackage(deb_files[0])
    deb_pkg.check()
    packages_needed = ' '.join(deb_pkg.missing_deps)
    (returncode, result, message) = run_shell_command('sudo apt-get -y install %s' % packages_needed, shell=True, show_stdout=True)
    if returncode != 0:
      raise RosGitBuildError("%s!!! Error building %s: can't install dependent packages %s" % (level_prefix, deb_package_name, packages_needed))
    (returncode, result, message) = run_shell_command('sudo dpkg -i %s' % deb_files[0], shell=True, show_stdout=True)
    if returncode != 0:
      raise RosGitBuildError("%s!!! Error building %s from %s: %s \n %s" % (level_prefix, deb_package_name, package_fetcher.url(package_name), 'debuild binary', message))
  else:
    raise RosGitBuildError("%s!!! Can't find a built debian package for %s after the build!" % (level_prefix, deb_package_name))

if __name__ == '__main__':
  args = parse_options()
  rd = Rosdistro('groovy')
  fetch = VcsPackageFetcher(rd, args.workspace)
  cache = apt.Cache()
  for package in args.packages:
    if package in rd.get_package_list():
      build_debian_package(fetch, package, cache, rd, get_dependencies=True)
    else:
      print('!!! Skipping nonexistent package %s' % (package))

