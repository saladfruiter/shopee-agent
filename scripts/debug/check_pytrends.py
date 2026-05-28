#!/usr/bin/env python3
import pytrends
print("pytrends dir:", dir(pytrends))
print("pytrends version:", getattr(pytrends, '__version__', 'unknown'))

# Check what's in the package
import inspect
for name in dir(pytrends):
    obj = getattr(pytrends, name)
    if inspect.ismodule(obj):
        print(f"  module: {name}")
    elif inspect.isclass(obj):
        print(f"  class: {name}")
