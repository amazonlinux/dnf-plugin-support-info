Name:           dnf-plugin-support-info
Version:        2.0.0
Release:        1%{?dist}
Summary:        DNF plugin for querying and displaying Amazon Linux package support information
BuildArch:      noarch

License:        GPL-2.0-only
URL:            https://github.com/amazonlinux/dnf-plugin-support-info
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  python3-devel
BuildRequires:  python3-pytest
BuildRequires:  python3-pytest-cov
BuildRequires:  python3-supportinfo
Requires:       python3-dnf
Requires:       python3-supportinfo

%description
DNF plugin for querying and displaying Amazon Linux package support
information. Provides the `dnf supportinfo` subcommand for looking up
per-package support state, dates, severities, and lifecycles.

%prep
%autosetup -n %{name}-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files dnf_support_info_plugin

# Install the example configuration to /etc/dnf/plugins/.
# Customise it (set baseurl, metadata_expire, etc.) per
# https://github.com/amazonlinux/dnf-plugin-support-info#plugin-configuration.
mkdir -p %{buildroot}%{_sysconfdir}/dnf/plugins
install -m 644 supportinfo.conf.example \
    %{buildroot}%{_sysconfdir}/dnf/plugins/supportinfo.conf

# Install the DNF plugin entry point into dnf's plugin directory.
mkdir -p %{buildroot}%{python3_sitelib}/dnf-plugins
cat > %{buildroot}%{python3_sitelib}/dnf-plugins/al_supportinfo.py << 'EOF'
from dnf_support_info_plugin.package_support import SupportInfoCommand
EOF

%check
%pytest test/

%files -f %{pyproject_files}
%license LICENSE
%doc NOTICE README.md
%config(noreplace) %{_sysconfdir}/dnf/plugins/supportinfo.conf
%{python3_sitelib}/dnf-plugins/al_supportinfo.py
%{python3_sitelib}/dnf-plugins/__pycache__/al_supportinfo.*.pyc

%changelog
* Fri May 22 2026 Eric Su <ericsuu@amazon.com> - 2.0.0-1
- Initial public release on GitHub under GPL-2.0-only
- Use SPDX license identifier
- Build via pyproject.toml; no longer bundles a default support_info.xml
  (administrators configure baseurl in /etc/dnf/plugins/supportinfo.conf)

* Fri Oct 14 2022 Nikhil Dikshit <nikhildi@amazon.com> - 1.0-2.amzn2022.0.3
- Updated support period for pcre

* Tue Oct 04 2022 Nikhil Dikshit <nikhildi@amazon.com> - 1.0-2.amzn2022.0.2
- Update support statements for GA
- Improve logic for querying package NVRs

* Tue Nov 16 2021 Nikhil Dikshit <nikhildi@amazon.com> - 1.0-2
- Provide support statements for all packages

* Tue Oct 05 2021 Nikhil Dikshit <nikhildi@amazon.com> - 1.0-1
- Initial build
