# Copyright: 2015 Tim Harder <radhermit@gmail.com>
# license GPL2/BSD 3

source "${PKGCORE_EBD_PATH}"/eapi/0.bash

__phase_src_compile() {
	if [[ -x ${ECONF_SOURCE:-.}/configure ]]; then
		econf
	fi
	if [[ -f Makefile || -f GNUmakefile || -f makefile ]]; then
		emake || die "emake failed"
	fi
}

:
