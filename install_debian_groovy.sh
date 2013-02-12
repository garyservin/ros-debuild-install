#! /bin/bash

echo "Debian Groovy Package-Based Installer"

EXPECTED_ARGS=1

if [ $# -ne $EXPECTED_ARGS ]; then
  echo "Usage: `basename $0` {variant}"
  echo "{variant} is usually desktop-full, desktop, or ros-base"
  echo " - but it could be anything from REP 131: http://ros.org/reps/rep-0131.html#variants"
  exit 65
fi

set -e
set +x

if [ -d ros-installer ]; then
  read -p "Warning: directory ros-installer exists, we will overwrite that directory [Y/n]?" -n 1
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborting!"
    exit 1
  fi
  # Start on a new line
  echo
else
  mkdir ros-installer
fi

cd ros-installer

#echo "* Building and installing catkin-pkg..."

#sudo apt-get -y install python-all debhelper python-stdeb dpkg-dev apt-file

#(
#git clone git://github.com/ros-infrastructure/catkin_pkg.git
#cd catkin_pkg
#python setup.py --command-packages=stdeb.command bdist_deb
#sudo dpkg -i deb_dist/*.deb
#)

echo "* Installing bootstrap and core library dependencies..."
sudo apt-get -y install build-essential python-yaml cmake subversion wget python-setuptools mercurial git-core bzr libapr1-dev libaprutil1-dev libbz2-dev python-dev libgtest-dev python-paramiko libboost-all-dev liblog4cxx10-dev pkg-config python-empy python-nose swig devscripts python-argparse libqt4-dev python-dateutil python-apt

function debian_package_installed() {
PACKAGE_NAME=$1
PACKAGE_VERSION=$2
(
  echo -n "Checking for ${PACKAGE_NAME}"
  set +e # we're using a non-zero return to tell us something
  if [ "x$PACKAGE_VERSION" != "x" ]; then
    echo -n " (Version ${PACKAGE_VERSION})... "
    dpkg -s ${PACKAGE_NAME} 2> /dev/null | grep -q "Version: ${PACKAGE_VERSION}"
    RESULT=$?
  else
    echo -n "... "
    dpkg -s ${PACKAGE_NAME} 2> /dev/null
    RESULT=$?
  fi
  set -e
  if [ $RESULT -ne 0 ]; then
    echo " Not found!"
    exit 1
  else
    echo " OK!"
    exit 0
  fi
)
return $?
}

function ros_bootstrap_package() {
PACKAGE_NAME=$1
PACKAGE_VERSION=$2
PACKAGE_URL=$3
(
  if ! debian_package_installed ${PACKAGE_NAME} ${PACKAGE_VERSION}; then
    echo "${PACKAGE_NAME} missing - downloading and installing.."
    filename=${PACKAGE_URL##*/}
    rm -f $filename
    set +e # We check the returns manually so we can display a message
    wget -qqq $PACKAGE_URL
    if [ $? -ne 0 ]; then
      echo "!!! Can't download a bootstrap package: $PACKAGE_URL"
      exit 1
    fi
    sudo dpkg -i $filename
    if [ $? -ne 0 ]; then
      echo "!!! Can't install a bootstrap package: $filename"
      exit 1
    fi
    set -e
  fi
)
return $?
}

echo "* Downloading and installing bootstrap packages..."
BASE_PACKAGES_URL="http://packages.ros.org/ros/ubuntu/"
# NOTE: order is important.
ros_bootstrap_package python-catkin-pkg 0.1.9 "${BASE_PACKAGES_URL}pool/main/c/catkinpkg/python-catkin-pkg_0.1.9-1_all.deb"
ros_bootstrap_package python-vcstools   0.1.28 "${BASE_PACKAGES_URL}pool/main/v/vcstools/python-vcstools_0.1.28-1_all.deb"
ros_bootstrap_package python-rosinstall 0.6.24 "${BASE_PACKAGES_URL}pool/main/r/rosinstall/python-rosinstall_0.6.24-1_all.deb"
ros_bootstrap_package python-rospkg     1.0.18 "${BASE_PACKAGES_URL}pool/main/r/rospkg/python-rospkg_1.0.18-1_all.deb"
ros_bootstrap_package python-rosdep     0.10.13 "${BASE_PACKAGES_URL}pool/main/r/rosdep/python-rosdep_0.10.13-1_all.deb"
ros_bootstrap_package python-wstool     0.0.2 "${BASE_PACKAGES_URL}pool/main/w/wstool/python-wstool_0.0.2-1_all.deb"

echo "* Bootstrapping rosdep..."

set +e # rosdep returns 1 if it's already initialized, but we don't care.
sudo rosdep init
set -e
rosdep update

if ! debian_package_installed "python-buildfarm"; then
  echo "* Missing python-buildfarm, downloading and building..."
  (
    sudo apt-get -y install python-stdeb
    git clone git://github.com/willowgarage/catkin-debs.git
    cd catkin-debs
    make deb_dist
    sudo dpkg -i deb_dist/python-buildfarm_0.0.1-1_all.deb
  )
fi

INSTALL_VARIANT=$1

echo "* Downloading list of packages in ${INSTALL_VARIANT}..."

VARIANT_YAML_URL="http://packages.ros.org/web/rosinstall/generate/raw/groovy/${INSTALL_VARIANT}"

wget -O packages.yaml $VARIANT_YAML_URL

PACKAGE_NAMES=`python -c "from yaml import load; print ' '.join([x['tar']['local-name'] for x in load(file('packages.yaml').read())])"`

echo "* Compiling and Installing ${INSTALL_VARIANT} packages: ${PACKAGE_NAMES}"

PACKAGES_IN_ORDER=$(python ../ros_gbp_ordering.py ${PACKAGE_NAMES} | tail -1)

echo "* In compilation order: ${PACKAGES_IN_ORDER}"

for package in ${PACKAGES_IN_ORDER}; do
  python ../ros_gbp_build_debians.py $package
done

echo "* All done :)"

echo "Don't forget to source the ros environment before you go on in the installation:"
echo 
echo "source /opt/ros/groovy/setup.sh"

