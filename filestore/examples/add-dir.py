#!/usr/bin/python3

#
# This script will add or update files in a directly (recursively)
# without copying the data into the datastore.  Unlike
# add-dir-simply.py it will use it's own file to keep track of what
# files are added to avoid the problem with duplicate files being
# re-added.
#
# This script will not clean out invalid entries from the filestore,
# for that you should use "filestore clean full" from time to time.
#

import sys
import os.path
import subprocess as sp

#
# Maximum length of command line, this may need to be lowerd on
# windows.
#

MAX_CMD_LEN = 120 * 1024


def main():
    #
    # Parse command line arguments
    #

    def print_err(*args, **kwargs):
        print(*args, file=sys.stderr, **kwargs)

    if len(sys.argv) != 3:
        print_err("Usage: ", sys.argv[0], "DIR CACHE")
        sys.exit(1)

    dir = sys.argv[1]
    if not os.path.isabs(dir):
        print_err("directory name must be absolute:", dir)
        sys.exit(1)

    cache = sys.argv[2]
    if not os.path.isabs(cache):
        print_err("cache file name must be absolute:", dir)
        sys.exit(1)

    #
    # Global variables
    #

    before = [] # list of (hash mtime path) -- from data file

    file_modified = set()
    hash_ok = {}

    already_have = set()
    toadd = {}


    #
    # Read in cache (if it exists) and determine any files that have modified
    #

    print("checking for modified files...")
    if os.path.exists(cache):

        try:
            f = open(cache)
        except OSError as e:
            print_err("count not open cache file: ", e)
            sys.exit(1)

        for line in f:
            hash,mtime,path = line.rstrip('\n').split(' ', 2)
            try:
                new_mtime = "%.6f" % os.path.getmtime(path)
            except OSError as e:
                print_err("skipping:", path, ":", e.strerror)
                continue
            before.append((hash,mtime,path),)
            if mtime != new_mtime:
                print("file modified:", path)
                file_modified.add(path)
            hash_ok[hash] = None

        del f

    #
    # Determine any hashes that have become invalid.  All files with
    # that hash will then be readded in an attempt to fix it.
    #

    print("checking for invalid hashes...")
    for line in Xargs(['ipfs', 'filestore', 'verify', '-v2', '-l3', '--porcelain'], list(hash_ok.keys())):
        line = line.rstrip('\n')
        _, status, hash, path = line.split('\t')
        hash_ok[hash] = status == "ok" or status == "appended" or status == "found"
        if not hash_ok[hash]:
            print("hash not ok:", status,hash,path)

    for hash,val in hash_ok.items():
        if val == None:
            print_err("WARNING: hash status unknown: ", hash)

    #
    # Open the new cache file for writing
    #

    if os.path.exists(cache):
        os.rename(cache, cache+".old")

    try:
        f = open(cache, 'w')
    except OSError as e:
        print_err("count not write to cache file: ", e)
        try:
            os.rename(cache+".old", cache)
        except OSError:
            pass
        sys.exit(1)

    #
    # Figure out what files don't need to be readded and write them
    # out to the cache.
    #

    for hash,mtime,path in before:
        if hash_ok.get(hash, True) == False or path in file_modified:
            # if the file still exists it will be picked up in the
            # directory scan so no need to do anything special
            pass
        else:
            already_have.add(path)
            print(hash,mtime,path, file=f)

    # To cut back on memory usage
    del before
    del file_modified
    del hash_ok

    #
    # Figure out what files need to be re-added
    #

    print("checking for files to add...")
    for root, dirs, files in os.walk(dir):
        for file in files:
            try:
                path = os.path.join(root,file)
                if path not in already_have:
                    if not os.access(path, os.R_OK):
                        print_err("SKIPPING", path, ":", "R_OK access check failed")
                        continue
                    mtime = "%.6f" % os.path.getmtime(path)
                    #print("will add", path)
                    toadd[path] = mtime
            except OSError as e:
                print_err("SKIPPING", path, ":", e)

    #
    # Finally, do the add.  Write results to the cache file as they are
    # added.
    #

    print("adding", len(toadd), "files...")

    errors = False

    class FilestoreAdd(Xargs):
        def __init__(self, args):
            Xargs.__init__(self, ['ipfs', 'filestore', 'add'], args)
        def process_ended(self, returncode):
            print("added", self.args_used, "files, ", len(self.args), "more to go.")

    for line in FilestoreAdd(list(toadd.keys())):
        try:
            _, hash, path = line.rstrip('\n').split(None, 2)
            mtime = toadd[path]
            del toadd[path]
            print(hash,mtime,path, file=f)
        except Exception as e:
            errors = True
            print_err("WARNING: problem when adding: ", path, ":", e)
            # don't abort, non-fatal error

    for path in toadd.keys():
        errors = True
        print_err("WARNING: ", path, "not added.")

    #
    # Cleanup
    #

    f.close()

    if errors:
        sys.exit(1)
    
class Xargs:
    def __init__(self, cmd, args):
        self.cmd = cmd
        self.args = args
        self.pipe = None
        self.args_used = -1
    
    def __iter__(self):
        return self
    
    def __next__(self):
        if self.pipe == None:
            self.launch()
        if self.pipe == None:
            raise StopIteration()
        line = self.pipe.stdout.readline()
        if line == '':
            self.close()
            return self.__next__()
        return line

    def launch(self):
        if len(self.args) == 0:
            return
        cmd_len = len(' '.join(self.cmd)) + 1
        i = 0
        while i < len(self.args):
            cmd_len += len(self.args[i]) + 1
            if cmd_len > MAX_CMD_LEN: break
            i += 1
        cmd = self.cmd + self.args[0:i]
        self.args_used = i
        self.args = self.args[i:]
        self.pipe = sp.Popen(cmd, stdout=sp.PIPE, bufsize=-1, universal_newlines=True)

    def close(self):
        pipe = self.pipe
        pipe.stdout.close()
        pipe.wait()

        self.process_ended(pipe.returncode)

        if pipe.returncode < 0:
            raise sp.CalledProcessError(returncode=pipe.returncode, cmd=pipe.args)

        self.pipe = None

    def process_ended(self, returncode):
        pass

if __name__ == "__main__":
    main()

