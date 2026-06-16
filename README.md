# dnf-plugin-support-info

DNF plugin that adds the `dnf supportinfo` subcommand. Use it to look up the
support status, dates, severities, and lifecycle phases of any package on
Amazon Linux 2023.

The plugin is a thin DNF integration over the
[`supportinfo`](https://github.com/amazonlinux/amazon-linux-supportinfo) Python
library, which does the actual XML parsing.

Just want to read the published support statements?
<https://docs.aws.amazon.com/linux/al2023/release-notes/support-info-by-support-statement.html>

## Requirements

* Amazon Linux 2023 (or another distribution that ships DNF and Python 3.9+)
* `python3-dnf` (provided by the OS)
* `python3-supportinfo` 1.0 or newer

## Installation

On Amazon Linux 2023, once the package is published:

```bash
sudo dnf install dnf-plugin-support-info
```

The package installs:

* The plugin code under `/usr/lib/python3.9/site-packages/dnf_support_info_plugin/`
* The DNF entry point at `/usr/lib/python3.9/site-packages/dnf-plugins/al_supportinfo.py`
* A starter config at `/etc/dnf/plugins/supportinfo.conf` (marked
  `%config(noreplace)`, so your edits survive package upgrades)

## Configuration

Edit `/etc/dnf/plugins/supportinfo.conf` before first use. At minimum, set
`baseurl` to point at the support-info XML you want the plugin to query.
A fully-commented example lives at
[`supportinfo.conf.example`](supportinfo.conf.example).

```ini
[main]
# Required. URL to the support_info XML file. DNF variables ($awsregion,
# etc.) are expanded automatically.
baseurl = https://my-bucket-$awsregion.s3.amazonaws.com/supportinfo.xml

# Optional. URL to the XSD schema used for validation.
templateurl = https://my-bucket-$awsregion.s3.amazonaws.com/supportinfo.xsd

# Optional. How long cached files stay valid, in seconds.
# Default: 1800 (30 minutes). -1 = never expire. 0 = always revalidate.
metadata_expire = 3600

# Optional. Verify a detached GPG signature on the downloaded XML before
# using it. The signature is fetched from baseurl + ".asc" automatically.
# Off by default. To turn on, set gpgcheck = 1 and add at least one gpgkey.
# Uses the same convention as the gpgcheck/gpgkey options on a DNF repo.
gpgcheck = 0
# gpgkey = file:///etc/pki/rpm-gpg/RPM-GPG-KEY-amazon-linux-2023

# Optional. When enabled, the plugin converts the downloaded 1.0-schema
# XML to the legacy (unversioned) format used by the previous version of
# this plugin. Off by default.
# legacy = 0
```

### Caching

When `metadata_expire` elapses, the plugin sends an HTTP conditional request
(ETag) and either extends the cache (HTTP 304) or downloads the new file
(HTTP 200). On network errors it falls back to the cached copy if one
exists. `dnf supportinfo --clean-cache` wipes the cache; `--sync` forces a
fresh download.

### URL schemes

`baseurl`, `templateurl`, and `gpgkey` accept `https://` and `file://` URLs.
Anything else is rejected at config-load time.

## Usage

```bash
dnf supportinfo --help
```

```
Supportinfo command-specific options:

  --pkg PACKAGE [PACKAGE ...]
                        Display support statements for one or more packages
  --showxml             Generate support info XML for a package
  --showjson            Generate support info JSON for a package
  --show FILTER [FILTER ...]
                        Filter packages by state (installed, available,
                        unavailable) and/or by support level name. Optional
                        prefixes "state:NAME" and "support:NAME" disambiguate.
  --clean-cache         Clear the remote file cache before running
  --list-filters        List every filter value accepted by --show
  --sync                Download and cache the latest support info XML now
```

### Look up packages

```bash
$ dnf supportinfo --pkg glibc

Name                      : glibc
Version                   : 2.34-52.amzn2023.0.7
State                     : installed
Current Status            : supported
Patch Priority            : default
Support Level Description : Default support for packages in Amazon Linux 2023
Covered Severities        : Low, Medium, Important, Critical
Support Timeline          : from 2023-03-15      : supported (Low, Medium, Important, Critical)
                          : from 2028-03-15      : unsupported
Support Statement         : Amazon Linux 2023 end-of-life
Link                      : https://aws.amazon.com/amazon-linux-ami/faqs/
```

`--pkg` accepts more than one package name:

```bash
dnf supportinfo --pkg glibc openssl-libs bash
```

### Filter the catalog

```bash
# All installed packages
dnf supportinfo --show installed

# Installed OR available (state filters are OR'ed together)
dnf supportinfo --show installed available

# Installed AND end-of-support (state + support-level filters are AND'ed)
dnf supportinfo --show installed eos

# Disambiguate when a name happens to match both groups
dnf supportinfo --show state:installed support:default

# What can I filter on?
dnf supportinfo --list-filters
```

### Get the raw data for a package

```bash
dnf supportinfo --pkg nodejs20 --showxml
dnf supportinfo --pkg nodejs20 --showjson
```

## Building from source

You'll need Python 3.9 or newer. The plugin imports `dnf` only at runtime
(unit tests mock it), so a regular development venv is fine.

```bash
# Make the supportinfo runtime dep available. Once it's on PyPI, plain
# `pip install supportinfo` will work; until then, install from a checkout.
pip install ../AmazonLinuxSupportInfo

# Editable install with test deps
pip install -e ".[test]"

pytest
```

### Build an RPM

The spec produces a noarch RPM targeting Amazon Linux 2023.

```bash
make sources
rpmbuild -ba \
  --define "_sourcedir $PWD" \
  --define "_srcrpmdir $PWD" \
  --define "_specdir $PWD" \
  dnf-plugin-support-info.spec
```

`make sources` writes `dnf-plugin-support-info-<version>.tar.gz` to the
current directory. The `--define` flags tell `rpmbuild` to look for the
tarball there instead of `~/rpmbuild/SOURCES`.

The build also requires `python3-supportinfo` (the runtime library) to be
available in the build environment.

## First run after install

A fresh install ships with the example config in place but no support data.
Set `baseurl=` in `/etc/dnf/plugins/supportinfo.conf`, then either:

```bash
sudo dnf supportinfo --sync          # populate the cache up front
```

or just run any `dnf supportinfo` command and let it fetch on demand.

## Reporting security issues

Do **not** open a GitHub issue. Use AWS's
[vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

GPL-2.0-only. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
