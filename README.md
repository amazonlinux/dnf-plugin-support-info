## Amazon Linux 2023: DNF Support Info Plugin

Just want to see the support statements? Head to https://docs.aws.amazon.com/linux/al2023/release-notes/support-info-by-support-statement.html

Amazon Linux provides updates for all packages and maintains compatibility within a major version for customer applications that are built on Amazon Linux. Core packages, such as glibc, openssl, openssh, and the dnf package manager, receive support for the lifetime of the major Amazon Linux 2023 release. Packages that aren't part of the core packages receive support defined by their upstream sources.

More information as to the maintenance support period of Amazon Linux 2023 can be found at [amazon-linux-2023/al2023-support-statements](https://github.com/amazonlinux/amazon-linux-2023/tree/main/al2023-support-statements).


### Plugin Usage:

In Amazon Linux 2023, you can see specific support status and dates of individual packages using the `dnf-plugin-support-info` plugin. You can even get information on all currently installed packages or apply filters based on "supported" or "unsupported" packages.

```

$ dnf supportinfo --help

Supportinfo command-specific options:

  --pkg PACKAGE         Display support statements for a package
  --showxml             Generate support info XML for a package
  --show {all,supported,unsupported,installed,available}
                        Display support statements for packages

```

### Display support information for a package:

```

$ dnf supportinfo --pkg php8.1

Name                 : php8.1
Version              : 8.1.23-1.amzn2023.0.1
State                : available
Support Status       : supported
Support Periods      : from 2023-03-15      : supported
                     : from 2024-11-25      : unsupported
Support Statement    : PHP 8.1 has security support until November 2024
Link                 : https://www.php.net/supported-versions
Other Info           : Support period for PHP 8.1 is the same as PHP 8.1 upstream end-of-life. PHP 8.2 is available with an
                     : upstream end-of-life date of 2025-12-08.
Package Note         : Upstream end-of-life for PHP 8.1 (php8.1) is 2024-11-25

```

```

$ dnf supportinfo --pkg glibc

Name                 : glibc
Version              : 2.34-52.amzn2023.0.7
State                : installed
Support Status       : supported
Support Periods      : from 2023-03-15      : supported
                     : from 2028-03-15      : unsupported
Support Statement    : Amazon Linux 2023 end-of-life
Link                 : https://aws.amazon.com/amazon-linux-ami/faqs/
Other Info           : This is the support statement for AL2023. The end-of-life of Amazon Linux 2023 is March 2028. From this
                     : point, the Amazon Linux 2023 packages will no longer receive any updates from AWS.

```

```

$ dnf supportinfo --pkg bcc

Name                 : bcc
Version              : 0.26.0-1.amzn2023.0.1
State                : available
Support Status       : supported
Support Periods      : from 2023-03-15      : supported
                     : from 2028-03-15      : unsupported
Support Statement    : Kernel has security support until March 2028
Link                 : https://aws.amazon.com/amazon-linux-ami/faqs/
Other Info           : There may be live patches available for a kernel for the first three months after it is released. Individual live
                     : patches don't get updates, but new live patches and new kernels may be released.
Package Note         : This package has a runtime dependency on kernel-libbpf, and thus also falls under the support statements for kernel.
                     : Amazon Linux will support a kernel until AL2023 End of Life

```

### Generate `support_info.xml` for a given package:

```plain

$ dnf supportinfo --pkg nodejs20 --showxml

<?xml version="1.0" ?>
<package_support current_as="2024-01-17">
  <statements>
    <statement id="eol_nodejs20" marker="supported" start_date="2023-12-11" end_date="2026-04-30">
      <summary>NodeJS 20 has security support until April 2026</summary>
      <text>Support period for NodeJS 20 differs from the main distribution end-of-life date.</text>
      <link>https://nodejs.org/en/about/previous-releases</link>
      <packages>
        <package name="nodejs20" nevra="20.10.0-1.amzn2023.0.1"/>
      </packages>
    </statement>
  </statements>
</package_support>

```

### List support statements for installed packages:

- **Note:** Available filters for listing support statemtents are: {all, supported, unsupported, installed, available}

```plain

$ dnf supportinfo --show installed

kernel                                     6.1.66-93.164.amzn2023               installed          supported          2028-03-15         Kernel has security support until March 2028
kernel-livepatch-repo-s3                   2023.3.20240108-0.amzn2023           installed          supported          2028-03-15         Kernel has security support until March 2028
acl                                        2.3.1-2.amzn2023.0.2                 installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
acpid                                      2.0.32-4.amzn2023.0.2                installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
alternatives                               1.15-2.amzn2023.0.2                  installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
amazon-chrony-config                       4.3-1.amzn2023.0.4                   installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
amazon-ec2-net-utils                       2.4.1-1.amzn2023.0.1                 installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
amazon-linux-repo-s3                       2023.3.20240108-0.amzn2023           installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
amazon-linux-sb-keys                       2023.1-1.amzn2023.0.5                installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
amazon-rpm-config                          228-3.amzn2023.0.2                   installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
amazon-ssm-agent                           3.2.1705.0-1.amzn2023                installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
at                                         3.1.23-6.amzn2023.0.2                installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
attr                                       2.5.1-3.amzn2023.0.2                 installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
audit-libs                                 3.0.6-1.amzn2023.0.2                 installed          supported          2028-03-15         Amazon Linux 2023 end-of-life

...
...
...

ghc-srpm-macros                            1.5.0-4.amzn2023.0.2                 installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
git                                        2.40.1-1.amzn2023.0.1                installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
git-core                                   2.40.1-1.amzn2023.0.1                installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
git-core-doc                               2.40.1-1.amzn2023.0.1                installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
glib2                                      2.74.7-689.amzn2023.0.2              installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
glibc                                      2.34-52.amzn2023.0.7                 installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
glibc-all-langpacks                        2.34-52.amzn2023.0.7                 installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
glibc-common                               2.34-52.amzn2023.0.7                 installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
glibc-gconv-extra                          2.34-52.amzn2023.0.7                 installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
glibc-locale-source                        2.34-52.amzn2023.0.7                 installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
gmp                                        6.2.1-2.amzn2023.0.2                 installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
gnupg2-minimal                             2.3.7-1.amzn2023.0.4                 installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
gnutls                                     3.8.0-377.amzn2023.0.3               installed          supported          2028-03-15         Amazon Linux 2023 end-of-life

...
...
...

zlib                                       1.2.11-33.amzn2023.0.5               installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
zram-generator                             1.1.2-67.amzn2023                    installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
zram-generator-defaults                    1.1.2-67.amzn2023                    installed          supported          2028-03-15         Amazon Linux 2023 end-of-life
zstd                                       1.5.5-1.amzn2023.0.1                 installed          supported          2028-03-15         Amazon Linux 2023 end-of-life

```

## License Summary

The sample code within this documentation is made available under the GPLv2.0 license. See the LICENSE file.

## Contributing

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.
