#!/bin/env python
prefix = '/' if len(sys.argv) < 2 else sys.argv[1]
print 'prefix', prefix
if prefix.endswith('/'):
    print list(__pack__.list(prefix[:-1]))
else:
    print __pack__.read(prefix)
