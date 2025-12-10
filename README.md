# Recovery Tools

Helper scripts for working with files recovered from deep disk scans. They avoid trusting filenames or filesystem timestamps and instead inspect file contents.

## rename-images.py
Renames/moves recovered images and videos based on creation timestamps read from metadata via PyExifTool.

Examples:
- Rename in place with verbose output:  
  `python3 rename-images.py -v /path/to/input`
- Rename and move into another directory:  
  `python3 rename-images.py /path/to/input /path/to/output`
- Dry run (no changes):  
  `python3 rename-images.py -n /path/to/input`

Behavior:
- Supported image/video formats per ExifTool metadata.
- Target names: `IMG_YYYY-MM-DD_hh-mm-ss.ext` for images, `MOV_...` for videos.
- Writes errors to `rename-errors.log` in the output dir (or current dir).

## rename-doc.py
Renames/moves recovered `.doc` files using internal creation/modification timestamps from the document content. If timestamps are missing, it prints available metadata and skips renaming.

Examples:
- Rename in place:  
  `python3 rename-doc.py /path/to/docs`
- Move into year-subfolders under an output dir:  
  `python3 rename-doc.py /path/to/docs /path/to/output`
- Dry run with verbose logging:  
  `python3 rename-doc.py -n -v /path/to/docs`

Behavior:
- Timestamps from OLE metadata; original name postfix preserved when present (`f1234_name.doc` -> `YYYY-MM-DD_hh-mm-ss_name.doc`).
- Errors logged to `rename-doc-errors.log` in the output dir (or current dir).

## validate-doc.py
Validates `.doc` files using multiple readers (olefile, hachoir, textract) and can filter output.

Examples:
- Default validation (prints VALID/INVALID):  
  `python3 validate-doc.py /path/to/docs`
- Only list invalid files:  
  `python3 validate-doc.py /path/to/docs --only-invalid`
- Show detailed validator output:  
  `python3 validate-doc.py -v /path/to/docs`
- Suppress recursive scan:  
  `python3 validate-doc.py --no-recursive /path/to/docs`
- Enable debug logging from parsers:  
  `python3 validate-doc.py --debug /path/to/docs`

Behavior:
- Marks files invalid if text extraction fails even when basic structure looks OK.
- Optional summary with `--summary`.

## Dependencies
See `requirements.txt` and install with:  
`python3 -m pip install -r requirements.txt`

## Using a virtual environment
It’s recommended to install dependencies in a virtual environment to avoid clashing with system packages.

Create and activate a venv:
```bash
python3 -m venv venv
source venv/bin/activate
```
Then install dependencies:
```bash
pip install -r requirements.txt
```
Deactivate when done:
```bash
deactivate
```
