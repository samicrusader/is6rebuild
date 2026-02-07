import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(
        description="Modify InstallShield cabinet files using i6comp replace commands"
    )
    parser.add_argument(
        "--iscab",
        default=r"C:\Users\samicrusader\Downloads\InstallShield_Cabinet_File_Viewer",
        help="Path to iscab.exe or directory containing it",
    )
    parser.add_argument(
        "--i6comp",
        default=r"C:\Users\samicrusader\Downloads\i6cmp13b",
        help="Path to i6comp.exe or directory containing it",
    )
    args = parser.parse_args()

    # Resolve executable paths
    iscab_exe = (
        args.iscab
        if args.iscab.endswith(".exe")
        else os.path.join(args.iscab, "iscab.exe")
    )
    i6comp_exe = (
        args.i6comp
        if args.i6comp.endswith(".exe")
        else os.path.join(args.i6comp, "i6comp.exe")
    )

    # Verify prerequisites
    for exe, name in [(iscab_exe, "iscab.exe"), (i6comp_exe, "i6comp.exe")]:
        if not os.path.exists(exe):
            print(f"Error: {name} not found at {exe}")
            sys.exit(1)

    if not os.path.exists("data1.cab"):
        print("Error: data1.cab not found in current directory")
        sys.exit(1)

    # Step 2: Read first 512 bytes of data1.cab
    with open("data1.cab", "rb") as f:
        data1_header = f.read(512)

    if len(data1_header) < 512:
        print("Error: data1.cab is smaller than 512 bytes")
        sys.exit(1)

    # Step 3: Copy files to temp directory within current directory
    temp_dir = tempfile.mkdtemp(dir=".")
    backup_files = ["data1.cab", "data1.hdr", "layout.bin"]

    try:
        for fname in backup_files:
            if os.path.exists(fname):
                shutil.copy2(fname, temp_dir)

        # Step 4: Execute i6comp with -f flag to get file paths with subdirectories
        result = subprocess.run(
            [i6comp_exe, "l", "-f", "data1.cab"],
            capture_output=True,
            text=True,
            check=True,
        )
        i6comp_output = result.stdout

        # Step 5: Extract uint32 from bytes 0x20-0x23 (little-endian)
        uint32_val = struct.unpack("<I", data1_header[0x20:0x24])[0]

        # Step 6: Parse i6comp output to find last Ind value
        matches = re.findall(r"(\d+),\s*\d+", i6comp_output)
        if not matches:
            print("Error: Could not parse Ind values from i6comp output")
            sys.exit(1)
        last_ind = int(matches[-1])

        # Step 7: Create data2.cab content in memory AND write to disk
        data2_content = bytearray(512)
        # 7a: Specific 28-byte header
        header_bytes = bytes.fromhex(
            "495363280C6000010000000000000000000000000002000000000070"
        )
        data2_content[0 : len(header_bytes)] = header_bytes
        pos = len(header_bytes)
        # 7b: uint32 from data1.cab
        data2_content[pos : pos + 4] = struct.pack("<I", uint32_val)
        pos += 4
        # 7c: last Ind as uint32
        data2_content[pos : pos + 4] = struct.pack("<I", last_ind)
        # 7d: Remaining bytes already zeroed
        # 7e: Kept in memory as data2_content

        # Write data2.cab to disk now so i6comp can modify it later if needed
        with open("data2.cab", "wb") as f:
            f.write(data2_content)

        # Step 8: Execute iscab to generate replace.ini
        subprocess.run(
            [iscab_exe, "data1.cab", "-ireplace.ini", "-lx"],
            check=True,
            capture_output=True,
        )

        # Step 9: Parse replace.ini to build file groups dictionary
        if not os.path.exists("replace.ini"):
            print("Error: replace.ini was not generated")
            sys.exit(1)

        file_groups = {}
        current_section = None
        skip_section = False

        with open("replace.ini", "r") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue

                if stripped.startswith("[") and stripped.endswith("]"):
                    section_name = stripped[1:-1]
                    current_section = section_name

                    if section_name == "ISCAB Info":
                        skip_section = True
                    elif section_name.startswith(("<Support>", "<Engine>", "<Disk1>")):
                        skip_section = True
                    else:
                        skip_section = False
                        file_groups[section_name] = []
                    continue

                if skip_section or current_section is None:
                    continue

                if stripped.startswith("File") and "=" in stripped:
                    value = stripped.split("=", 1)[1].strip()
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    file_groups[current_section].append(value)

        # Build mapping from i6comp -f output: (group, relative_path) -> (index, full_path)
        # Format with -f flag: Date Time OrigSize Attr CompSize Ind,Vol Group\Subdir\File
        group_file_info = {}
        for line in i6comp_output.splitlines():
            match = re.search(
                r"\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}\s+\d+\s+\S+\s+\d+\s+(\d+),\s*\d+\s+(.+)$",
                line,
            )
            if match:
                idx, file_path = match.groups()
                file_path = file_path.strip()

                # Parse group and relative path from full path
                if "\\" in file_path:
                    parts = file_path.split("\\", 1)
                    group_name = parts[0]
                    relative_path = parts[1]
                else:
                    group_name = ""
                    relative_path = file_path

                group_file_info[(group_name, relative_path)] = (int(idx), file_path)

        # Step 10: Collect all replacements, then sort by index naturally
        replacements = []
        for group, files in file_groups.items():
            for relative_path in files:
                key = (group, relative_path)

                if key not in group_file_info:
                    print(f"Warning: Could not find index for {group}/{relative_path}, skipping")
                    continue

                idx, full_cab_path = group_file_info[key]

                # For err_ groups, use current directory (English files available locally)
                # For other groups, use the full subdirectory path from cabinet
                if group.startswith("err_"):
                    source_path = os.path.basename(relative_path)
                else:
                    source_path = full_cab_path

                replacements.append((idx, group, relative_path, source_path))

        # Sort by index (natural/numerical order)
        replacements.sort(key=lambda x: x[0])

        # Execute replacements in sorted order
        for idx, group, relative_path, source_path in replacements:
            # Logging and execution as specified
            #print(f"Replacing index {idx} ({group}/{relative_path}) with {source_path}")
            print(' '.join([i6comp_exe, "r", "data1.cab", str(idx), source_path]))
            result = subprocess.run(
                [i6comp_exe, "r", "data1.cab", str(idx), source_path],
                check=True,
                capture_output=True,
            )
            #if result.stdout:
                #print(result.stdout.decode('oem', errors='ignore'))

        # Step 11: Replace first 512 bytes in data2.cab with the in-memory content from step 7
        with open("data2.cab", "r+b") as f:
            f.seek(0)
            f.write(data2_content)

        print("data2.cab created successfully")

    finally:
        # Step 12: Cleanup and restore original files
        if os.path.exists("replace.ini"):
            os.remove("replace.ini")

        for fname in backup_files:
            backup_path = os.path.join(temp_dir, fname)
            if os.path.exists(backup_path):
                shutil.copy2(backup_path, fname)

        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
