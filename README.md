# Debian ROS Groovy easy install script

This script is meant to make it easy to set up a deb-based install on a non-Ubuntu system that is still debian-based.  I've been using it to install packages from the [ROS gbp repository set][1] for a little while now, and bootstrapping new installs on Debian.

[1]: https://github.com/ros-gbp

I've tested it on:

 * Debian sid
 * Debian wheezy

It gets you basically to step 2.2 in the [Source installation][3] instructions, you will have to build your rosbuild packages
on your own.

[3]: http://ros.org/wiki/groovy/Installation/Source#Build_the_rosbuild_Packages

# How to use

Initial setup:

    git clone git://github.com/jamuraa/ros-groovy-debuild-install
    cd ros-groovy-debuild-install
    bash install_debian_groovy.sh desktop

At this point, walking away for a little while is not a bad idea.  It takes a long time (hours) to download, compile and install these debs.  If you need to reboot or stop the work for some reason, you can stop this script with Ctrl-C at pretty much any time, and come back and run the last line again, it should pick up reasonably near to where it left off.

You can use any of the [REP 131][2] variants in place of desktop.  I usually start with the bare-bones install (ros\_comm) and then go from there.

[2]: http://ros.org/reps/rep-0131.html#variants

Later package installs:

    python ros_gbp_build_debians.py <packagename>

This will check the dependencies, download, build and install any dependencies required for the package named `<packagename>`.
It has the same properties as the previous initial setup, so you can stop it and it will know from there on.

