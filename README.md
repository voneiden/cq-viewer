# cq-viewer

cq-viewer follows the footsteps of [CQ-Editor](https://github.com/cadquery/CQ-Editor). 

Mainly for testing out some ideas that I have and well, just a lean tool for the job that I need myself.

* using wx instead of qt
* no editing
* dimension measurement and midpoints
* support cadquery and build123d

Heavily work in progress and currently runs on linux only.
## attrdict errors

If you encounter

> ModuleNotFoundError: No module named 'attrdict'

or 
> pip._internal.exceptions.MetadataGenerationFailed: metadata generation failed

install attrdict3 manually

```bash
pip install attrdict3
```
