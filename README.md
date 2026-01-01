# Recovery Tools

Helper scripts for working with files recovered from deep disk scans. They avoid trusting filenames or filesystem
timestamps and instead inspect file contents.

These scripts were developed when a family member quick formatted a harddrive. I used several recovery tools in differnt
modes to get the files back and ended up with several large collections that should be merged into one.
These script are made to automate as much as that process as possible.

The scripts were developed and tested on real data. I may not have hit all corner cases and some may come from 
recovery tools I have not used.
Start by using the dry run modes and veryfy the result before deleting files.

These scripts were mostly developed using AI but verified by a human. When I found errors they were corrected
and in several cases the AI chose suboptimal algorithms where I had to describe the algorithm. I did not make
an efford to ensure good gode structure, although all scripts are so small that is less of an issue.

## Process of recovering files

- Use several recovery tools like photorec (free software) and DiskDrill (commercial) to crate several folders
   each with a collection of files in various states.

- Fastest path
  - Use total-meta-collector.py that will do all the things, that the scripts in the stepwise
    path will do. It will just be a lot faster because each file is only read once and not multiple
    times.

- Stepwise path
  - Use rename-zero-files.py to rename files only containing binary zeros to .damaged.

  - Use mkfilesize-tables.py to make files named filesizes. These can be used by replace-damaged-files.py to
    make a good guess on the contents of damaged files.

  - Use replace-damaged-files.py to either automatically replaced damaged files with good candidates
    or generate a list so you do it manually.

  - Use mkhashes.py to creates a hashes.txt files in the root of each collection.

- Use deduplicate.py to delete files from lesser important collections if they exists in more important collections.
  A more important collection may be one that has many files names recovered, wile a lesser imprtant collection is
  one with a lot of contents but no file names recovered.

- Manually try to combine the different collections, by taking files from collections without proper file names
  and placing them in the final collection. .damaged files may indicate the names and size of a file, which may
  make it easier to place a file without a proper file name in its exact file name.
  This process is highly manual and require some human memory and guess work.

- Use tools like rename-images.py and rename-doc.py to rename certain file types to names that provides some
  information and organization, without being the original names.
   

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

## extract-ddscan.py
Extracts files from a raw disk image using a ddscan SQLite database.
This script did never work properly, as the Disk Drill database was not
fully reverse engineered.

Examples:
- Extract everything:  
  `python3 extract-ddscan.py -i disk.img -d ddscan.db -o out_dir`
- Limit to 50 files and filter with a WHERE clause:  
  `python3 extract-ddscan.py -i disk.img -d ddscan.db -o out_dir -n 50 -w "size > 0" -v`
- Preview without writing files:  
  `python3 extract-ddscan.py -i disk.img -d ddscan.db -o out_dir --dry-run`

Behavior:
- Reads `block` and `size` from `files` table; offset = `block * 512`.
- De-dupes entries sharing the same `block/size` pair.
- Saves to `<output>/<path-dir>/<extension>/<name>` using `paths.path` for the directory and the filename extension (or `no_ext`).
- Preserves modification time from the `date` field when present.

## hexless.py

Program that shows a files contents in hexa decimal format. Is good to see if a file contains only binary
zeros or is damaged in any way.

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
