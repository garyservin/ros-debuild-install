#!/usr/bin/env python

import argparse
from catkin_pkg.package import parse_package_string

from rosdistro import get_index
from rosdistro import get_index_url
from rosdistro import get_release_cache

def parse_options():
  parser = argparse.ArgumentParser(description = 'List ROS packages that need to be installed to build a set of packages.'
      'Packages are listed in a correct build order.')
  parser.add_argument('--workspace', dest='workspace', default='./tmp_workspace',
      help='A directory where repositories will be checked out into.')
  parser.add_argument('--distro', dest='distro', default='groovy',
      help='The ros distro. electric, fuerte, groovy, hydro')
  parser.add_argument(dest='packages', nargs='+')
  args = parser.parse_args()
  return args

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

def get_packages_dependencies(package_names, distro):
  """Gets a set of dependencies for packages to build and run the packages named.
Returns a dict with keys of package names whose values are the set of packages
which that package requires to build."""

  from collections import deque

  package_dependencies = {}
  packages_to_process = deque(package_names)
  while len(packages_to_process) > 0:
    pkg_name = packages_to_process.popleft()
    if pkg_name in package_dependencies:
      continue
    if pkg_name not in distro.package_xmls:
      raise "Can't find package %s in the distro cache" % (pkg_name)
    pkg = parse_package_string(distro.package_xmls[pkg_name])

    package_dependencies[pkg_name] = set([p.name for p in (pkg.buildtool_depends + pkg.build_depends + pkg.run_depends) if p.name in distro.package_xmls])
    for name in package_dependencies[pkg_name]:
      packages_to_process.append(name)

  return package_dependencies

def package_build_order(package_names, distro_name='groovy'):
  distro = get_release_cache(get_index(get_index_url()), distro_name)
  packs = get_packages_dependencies(package_names, distro)

  from itertools import chain
  return chain.from_iterable(toposort2(packs))

if __name__ == '__main__':
  args = parse_options()
  print ' '.join(package_build_order(args.packages, args.distro))

