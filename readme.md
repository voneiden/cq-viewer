# cq-viewer

cq-viewer follows the footsteps of [CQ-Editor](https://github.com/cadquery/CQ-Editor). 

It serves as a testbed for my own ideas like:

* using wx instead of qt
* no editing
* Workplane history browsing
* Integration with [cq-filter](https://github.com/voneiden/cq-filter)
* Dimension measurement

## cq-filter integration (idea)

It could be interesting to be able to select for example face(s) in the viewer and get the 
code required to select them on the workplane.

The easiest way to do this could be with HashCode, however that does not suit parametric models
as the HashCode will change if an underlying parameter changes, breaking the model.

I suppose in theory it should be possible to use some heuristics to generate
a cq-filter queries that match with some kind of reliability even in parametric situations.

## attrdict errors

If you encounter

> ModuleNotFoundError: No module named 'attrdict'

or 
> pip._internal.exceptions.MetadataGenerationFailed: metadata generation failed

install attrdict3 manually

```bash
pip install attrdict3
```
