# is6rebuild

Lazy scripts I generated with Kimi K2.5 to rebuild 2-disk (data1.cab, data2.cab) installers that are missing the second disk (as stored in InstallShield Installation Information)

You need i6comp 1.3b: https://www.sac.sk/download/pack/i6cmp13b.zip and ISCab: https://dl.dropboxusercontent.com/s/juxy8fc79ccfqra/InstallShield_Cabinet_File_Viewer.zip

test.py rebuilds using ISCab (better for larger files as i6comp only supports really legacy compression) and test2.py rebuilds using i6comp (which gives me better control over what files to modify)

This has only been tested for data2.cab, no further disks are supported. test.py expects all files to be in the directory the script is run from, test2.py expects the files to be in a directory structure matching the file group and stored-filename (including subdirectories).
