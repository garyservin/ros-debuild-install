#! /bin/bash

echo "Debian ROS Package-rebuilding Installer"

EXPECTED_ARGS=2

if [ $# -ne $EXPECTED_ARGS ]; then
  echo "Usage: `basename $0` {release} {variant}"
  echo "{release} is groovy or hydro"
  echo "{variant} is usually ros_comm, desktop-full, or desktop"
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
sudo apt-get -y install build-essential python-yaml cmake subversion wget \
  python-setuptools mercurial git-core bzr libapr1-dev libaprutil1-dev \
  libbz2-dev python-dev libgtest-dev python-paramiko libboost-all-dev \
  liblog4cxx10-dev pkg-config python-empy python-nose swig devscripts \
  python-argparse libqt4-dev python-dateutil python-apt python-docutils curl

function debian_package_installed() {
PACKAGE_NAME=$1
PACKAGE_VERSION=$2
(
  echo -n "Checking for ${PACKAGE_NAME}"
  set +e # we are using a non-zero return to tell us something
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
SOURCE_PACKAGE_NAME=$1
PACKAGE_NAME=$2
BASE_PACKAGE_URL=$3
(
  PACKAGE_LIST_URL=${BASE_PACKAGES_URL}pool/main/${SOURCE_PACKAGE_NAME:0:1}/${SOURCE_PACKAGE_NAME}
  PACKAGE_VERSION=$(curl -ss ${PACKAGE_LIST_URL}/ | grep -o -E "[0-9]{1,2}.[0-9]{1,2}.[0-9]{1,2}-[0-9]{1,2}" | tail -1)

  if ! debian_package_installed ${PACKAGE_NAME} ${PACKAGE_VERSION}; then
    PACKAGE_URL=${PACKAGE_LIST_URL}/${PACKAGE_NAME}_${PACKAGE_VERSION}_all.deb
    echo "${PACKAGE_NAME} missing - downloading and installing from ${PACKAGE_URL}.."
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
ros_bootstrap_package catkinpkg  python-catkin-pkg ${BASE_PACKAGES_URL}
ros_bootstrap_package vcstools   python-vcstools   ${BASE_PACKAGES_URL}
ros_bootstrap_package rospkg     python-rospkg     ${BASE_PACKAGES_URL}
ros_bootstrap_package rosdistro  python-rosdistro  ${BASE_PACKAGES_URL}
ros_bootstrap_package rosinstall python-rosinstall ${BASE_PACKAGES_URL}
ros_bootstrap_package rosinstallgenerator python-rosinstall-generator ${BASE_PACKAGES_URL}
ros_bootstrap_package rosdep     python-rosdep     ${BASE_PACKAGES_URL}
ros_bootstrap_package wstool     python-wstool     ${BASE_PACKAGES_URL}

echo "* Bootstrapping rosdep..."

set +e # rosdep returns 1 if it's already initialized, but we don't care.
sudo rosdep init
set -e
rosdep update

if ! debian_package_installed "python-buildfarm"; then
  echo "* Missing python-buildfarm, downloading and building..."
  (
    sudo apt-get -y install python-stdeb
    git clone git://github.com/ros-infrastructure/buildfarm
    cd buildfarm
    make deb_dist
    sudo dpkg -i deb_dist/python-buildfarm_0.0.1-1_all.deb
  )
fi

ROSRELEASE_NAME=$1
INSTALL_VARIANT=$2

echo "* Generating list of packages in ${ROSRELEASE_NAME} ${INSTALL_VARIANT}..."

#VARIANT_YAML_URL="http://packages.ros.org/web/rosinstall/generate/raw/${ROSRELEASE_NAME}/${INSTALL_VARIANT}"
#wget -O packages.yaml $VARIANT_YAML_URL

rosinstall_generator ${INSTALL_VARIANT} --rosdistro ${ROSRELEASE_NAME} --deps --wet-only > packages.yaml

PACKAGE_NAMES=`python -c "from yaml import load; print ' '.join([x['git']['local-name'] for x in load(file('packages.yaml').read())])"`

echo "* Compiling and Installing ${ROSRELEASE_NAME} ${INSTALL_VARIANT} packages: ${PACKAGE_NAMES}"

PACKAGES_IN_ORDER=$(python ../ros_gbp_ordering.py --distro ${ROSRELEASE_NAME} ${PACKAGE_NAMES} | tail -1)

echo "* In compilation order: ${PACKAGES_IN_ORDER}"

for package in ${PACKAGES_IN_ORDER}; do
  python ../ros_gbp_build_debians.py --distro ${ROSRELEASE_NAME} $package
done

echo "* All done :)"

echo "Don't forget to source the ros environment before you go on in the installation:"
echo 
echo "source /opt/ros/${ROSRELEASE_NAME}/setup.sh"

