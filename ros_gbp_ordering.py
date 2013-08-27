#!/usr/bin/env python

import os.path
import copy
import shutil
import time
import logging
import sys
import urllib2
import argparse

import yaml
import os.path

from vcstools.git import GitClient
from vcstools.vcs_base import VcsError
import catkin_pkg.package as catpak
from catkin_pkg.package import InvalidPackage

import rospkg.distro
from buildfarm.ros_distro import Rosdistro, debianize_package_name
from buildfarm.dependency_walker import VcsFileCache

def github_get_file_contents(url, version, filename):
  # https://github.com/ros-gbp/ros_comm-release/raw/release/topic_tools/1.9.19/package.xml
  # replace git:// with https://
  new_url = url.replace('git://', 'https://')
  # cut the .git off the end
  new_url = new_url.replace('.git', '')
  # add the /raw, package version, and file path.
  new_url = new_url + '/raw/' + version + '/' + filename
  print('Getting github url %s instead' % new_url)
  return urllib2.urlopen(new_url).read()

def parse_options():
  parser = argparse.ArgumentParser(description = 'List ROS packages that need to be installed to build a set of packages.'
      'Packages are listed in a correct build order.')
  parser.add_argument('--workspace', dest='workspace', default='./tmp_workspace',
      help='A directory where repositories will be checked out into.')
  parser.add_argument('--distro', dest='distro', default='groovy',
      help='The ros distro. electric, fuerte, groovy, hydro')
  parser.add_argument('--ignore-cache', dest='ignore_cache', default=False, action="store_true",
      help='Ignore the packages.xml cache and refresh all dependency info.')
  parser.add_argument(dest='packages', nargs='+')
  args = parser.parse_args()
  return args

class VcsPackagesCache(object):
  """Caches the packages.xml of packages so we don't need to refetch them"""

  def __init__(self, cachefile=None):
    if cachefile is None:
      self.cachefile = os.path.join(os.path.expanduser('~'), '.ros', 'packagexmlcache.yaml')
    else:
      self.cachefile = cachefile
    self.reload_from_file()

  def reload_from_file(self):
    try:
      f = open(self.cachefile)
      self.cached = yaml.safe_load(f)
      f.close()
    except (IOError, yaml.parser.ParserError):
      self.cached = dict()
    if not isinstance(self.cached, dict):
      # something got messed up. clear the cache.
      self.cached = dict()

  def write_to_file(self):
    try:
      f = open(self.cachefile, 'w')
      yaml.dump(self.cached, f)
      f.close()
    except IOError:
      pass # meh.

  def _make_key(self, name, version):
    return '%s:%s' % (name, version)

  def store(self, name, version, pkg_string):
    self.cached[self._make_key(name, version)] = pkg_string
    self.write_to_file()

  def get(self, name, version):
    return self.cached.get(self._make_key(name, version), None)


class VcsPackagesInfo(object):
  """Provides package information from rosdistro repositories."""

  def __init__(self, rd_obj, vcs_cache, packages_cache=None):
    self.checkout_info = rd_obj.get_package_checkout_info()
    self.rosdistro = rd_obj._rosdistro
    self.vcs_cache = vcs_cache
    self.xml_cache = packages_cache
    self.packages = {}
    # TODO: in the future, store the XMLs so that we don't have to refetch repositories?
    # self.package_xmls = {}
    self.urls_updated = set([])

  def get_package(self, package_name):
    if package_name in self.packages:
      return self.packages[package_name]
    pkg_info = self.checkout_info[package_name]
    pkg_string = None
    if self.xml_cache is not None:
      maybe_cached = self.xml_cache.get(package_name, pkg_info['version'])
      if maybe_cached is None:
        maybe_cached = self.xml_cache.get(package_name, pkg_info['full_version'])
      if maybe_cached is not None:
        print('Found %s (version %s) in package.xml cache..' % (package_name, pkg_info['version']))
        pkg_string = maybe_cached
    if pkg_string is None:
      url = pkg_info['url']
      url_fetched_before = url in self.urls_updated
      self.urls_updated.add(url)
      self.vcs_cache._skip_update = url_fetched_before
      print "%s (version %s) not in cache, fetching package.xml..." % (package_name, pkg_info['version'])
      try:
        pkg_string = self.get_package_xml(url, pkg_info['full_version'])
      except: # This is probably because full_version is wrong.  Try again with the regular version.
        try:
          pkg_string = self.get_package_xml(url, pkg_info['version'])
        except VcsError as ex:
          print("Failed to get package.xml for %s.  Error: %s" % (package_name, ex))
          raise ex
      if self.xml_cache is not None:
        self.xml_cache.store(package_name, pkg_info['full_version'], pkg_string)
      if not self.vcs_cache._skip_update:
        #print("Sleeping 1s to avoid github throttling..")
        time.sleep(1)
    try:
      p = catpak.parse_package_string(pkg_string)
      self.packages[p.name] = p
    except InvalidPackage as ex:
      print('package.xml for %s is invalid.  Error: %s' % (package_name, ex))
    return p

  def get_package_xml(self, url, version):
    if url.startswith('git://github.com/') or url.startswith('https://github.com/'):
      try:
        return github_get_file_contents(url, version, 'package.xml')
      except: # Okay, Let's just try the VCS way instead then.
        pass
    return self.vcs_cache.get_file_contents('git', url, version, 'package.xml')

  def __getitem__(self, key):
    if not self.exists(key):
      raise KeyError()
    return self.get_package(key)

  def __contains__(self, item):
    return self.exists(item)

  def exists(self, package_name):
    return package_name in self.checkout_info

def prune_self_depends(packages, package):
  if package.name in [p.name for p in packages]:
    print("ERROR: Recursive dependency of %s on itself, pruning this dependency" % (package.name))
    for p in packages:
      if p.name == package.name:
        packages.remove(p)
        break

def _get_depends(packages, package, recursive=False, buildtime=False):
  if buildtime:
    immediate_depends = set([packages[d.name] for d in package.build_depends if d.name in packages] + [packages[d.name] for d in package.buildtool_depends if d.name in packages])
  else:
    immediate_depends = set([packages[d.name] for d in package.run_depends if d.name in packages])
  prune_self_depends(immediate_depends, package)

  result = copy.copy(immediate_depends)

  if recursive:
    for d in immediate_depends:
      if d.name in packages:
        result |= _get_depends(packages, d, recursive, buildtime)
        prune_self_depends(result, package)
      else:
        print("skipping missing dependency %s. not in packages!" % (d.name))

  return result

def toposort2(data):
  """Dependencies are expressed as a dictionary whose keys are items
and whose values are a set of dependent items. Output is a list of
sets in topological order. The first set consists of items with no
dependences, each subsequent set consists of items that depend upon
items in the preceeding sets.

>>> print '\\n'.join(repr(sorted(x)) for x in toposort2({
...     2: set([11]),
...     9: set([11,8]),
...     10: set([11,3]),
...     11: set([7,5]),
...     8: set([7,3]),
...     }) )
[3, 5, 7]
[8, 11]
[2, 9, 10]
"""
  from functools import reduce

  # Ignore self dependencies.
  for k, v in data.items():
    v.discard(k)
  # Find all items that don't depend on anything.
  extra_items_in_deps = reduce(set.union, data.itervalues()) - set(data.iterkeys())
  # Add empty dependences where needed
  for item in extra_items_in_deps:
    data[item] = set()
  # Not available in Py2.6 data.update({item:set() for item in extra_items_in_deps})
  while True:
    ordered = set(item for item, dep in data.iteritems() if not dep)
    if not ordered:
      break
    yield ordered
    newdata = dict()
    for item, dep in data.iteritems():
      if item not in ordered:
        newdata[item] = (dep - ordered)
    data = newdata
    # No list comprehensions in Py2.6
    #   data = {item: (dep - ordered)
    #        for item, dep in data.iteritems()
    #            if item not in ordered}
  assert not data, "Cyclic dependencies exist among these items:\n%s" % '\n'.join(repr(x) for x in data.iteritems())

def get_packages_dependencies(package_names, workspace, rd_obj, package_cache=None):
  """Gets a set of dependencies for packages to build and run the packages named.
Returns a dict with keys of package names whose values are the set of packages
which that package requires to build."""

  from collections import deque
  vcs_cache = VcsFileCache(workspace, skip_update=False);
  package_info = VcsPackagesInfo(rd_obj, vcs_cache, package_cache)

  urls_updated = set([])

  package_dependencies = {}
  packages_to_process = deque(package_names)
  while len(packages_to_process) > 0:
    pkg_name = packages_to_process.popleft()
    if pkg_name in package_dependencies:
      continue
    p = package_info.get_package(pkg_name)
    deb_name = debianize_package_name(rd_obj._rosdistro, p.name)

    package_dependencies[pkg_name] = set([p.name for p in (_get_depends(package_info, p, recursive=False, buildtime=True) | _get_depends(package_info, p, recursive=False, buildtime=False))])
    for name in package_dependencies[pkg_name]:
      packages_to_process.append(name)

  return package_dependencies

def package_build_order(package_names, workspace_path, distro_name='groovy', package_cache=None):
  rd = Rosdistro('groovy')
  packs = get_packages_dependencies(package_names, workspace_path, rd, package_cache)

  from itertools import chain
  return chain.from_iterable(toposort2(packs))

if __name__ == '__main__':
  args = parse_options()
  packagexml_cache = None
  if not args.ignore_cache:
    packagexml_cache = VcsPackagesCache()
  print ' '.join(package_build_order(args.packages, args.workspace, distro_name=args.distro, package_cache=packagexml_cache))

