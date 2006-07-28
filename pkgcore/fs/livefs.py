# Copyright: 2005 Brian Harring <ferringb@gmail.com>
# License: GPL2

"""
interaction with the livefs, namely generating fs objects to represent the livefs
"""

import os, collections
from stat import S_IMODE, S_ISDIR, S_ISREG, S_ISLNK, S_ISFIFO, S_ISCHR, S_ISBLK
from pkgcore.fs.fs import fsFile, fsDir, fsSymLink, fsDev, fsFifo
from pkgcore.fs.util import normpath
from pkgcore.fs.contents import contentsSet
from pkgcore.chksum import get_handlers
from pkgcore.util.mappings import LazyValDict

__all__ = ["gen_obj", "scan", "iter_scan"]


def gen_chksums(handlers, location):
	def f(key):
		return handlers[key](location)
	return LazyValDict(handlers, f)


def gen_obj(path, stat=None, chksum_handlers=None, real_path=None):
	
	"""
	given a fs path, and an optional stat, return an appropriate fs obj representing that file/dir/dev/fif/link

	@param stat: stat object to reuse if available
	@param real_path: real path to the object if path is the desired location
	@raise KeyError: if no obj type matches the stat checks
	@return: L{pkgcore.fs.fs.fsBase} derivative
	"""

	if real_path is None:
		real_path = path
	if stat is None:
		stat = os.lstat(real_path)
	if chksum_handlers is None:
		chksum_handlers = get_handlers()

	mode = stat.st_mode
	d = {"mtime":stat.st_mtime, "mode":S_IMODE(mode), "uid":stat.st_uid, "gid":stat.st_gid, "real_path":real_path}
	if S_ISDIR(mode):
		return fsDir(path, **d)
	elif S_ISREG(mode):
		d["size"] = stat.st_size
		if real_path is None:
			l = path
		else:
			l = real_path
		return fsFile(path, chksums=gen_chksums(chksum_handlers, l), **d)
	elif S_ISLNK(mode):
		d["target"] = os.readlink(real_path)
		return fsSymLink(path, **d)
	elif S_ISFIFO(mode):
		return fsFifo(path, **d)
	elif S_ISCHR(mode) or S_ISBLK(mode):
		return fsDev(path, **d)
	else:
		raise KeyError(path)


# hmm. this code is roughly 25x slower then find.
# make it less slow somehow.  the obj instantiation is a bit of a killer I'm afraid;
# without obj, looking at 2.3ms roughly best of 3 100 iterations, obj instantiation, 58ms.
# also, os.path.join is rather slow.
# in this case, we know it's always pegging one more dir on, so it's fine doing it this way
# (specially since we're relying on os.path.sep, not '/' :P)

def iter_scan(path, offset=None):
	"""
	generator that yield L{pkgcore.fs.fs.fsBase} objects from recursively scanning a path.
	Does not follow symlinks pointing at dirs, just merely yields an obj representing said symlink

	@param path: str path of what directory to scan in the livefs
	@param offset: if not None, prefix to strip from each objects location.  if offset is /tmp, /tmp/blah becomes /blah
	"""
	chksum_handlers = get_handlers()
	sep = os.path.sep
	if offset is None:
		offset = ""
		dirs = collections.deque([path.rstrip(sep)])
		yield gen_obj(dirs[0], chksum_handlers=chksum_handlers)
	else:
		offset = normpath(offset.rstrip(sep))+sep
		path = normpath(path)
		dirs = collections.deque([path.rstrip(sep)[len(offset):]])
		if dirs[0]:
			yield gen_obj(dirs[0], chksum_handlers=chksum_handlers)

	while dirs:
		base = dirs.popleft() + sep
		for x in os.listdir(offset + base):
			path = base + x
			o = gen_obj(path, chksum_handlers=chksum_handlers, real_path=offset+path)
			yield o
			if isinstance(o, fsDir):
				dirs.append(path)

def scan(*a, **kw):
	"""
	calls list(iter_scan(*a, **kw))
	Look at iter_scan for valid args
	"""
	return contentsSet(iter_scan(*a, **kw))
