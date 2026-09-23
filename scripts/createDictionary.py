#!/usr/bin/python3

import sys
import traceback
from pathlib import Path

import utils
import output_processing
import input_handlers
import markup
from errors import DictionaryBuildError
from stats import StatsBuilder


def write_stats_to_file(stats_builder: StatsBuilder, output_filename: str) -> None:
    per_file_stats = stats_builder.get_full_stats()
    total, syns, bad = 0, 0, 0

    with open(output_filename, 'w', encoding='utf-8') as f:
        for filename, (n_entries, n_syns, n_bad, _) in sorted(per_file_stats.items()):
            stat_parts = [str(n_entries), str(n_syns)]
            total += int(n_entries)
            syns += int(n_syns)

            if n_bad > 0:
                stat_parts.append(str(n_bad))
                bad += int(n_bad)

            f.write(f"{filename}: {', '.join(stat_parts)}\n")
        f.write(f"TOTAL: {total}, {syns} (synonly: {syns-total}){f', {bad}' if bad else ''}\n")


def parse_bool_header(value: str, key: str, file_path) -> bool:
    normalized = value.strip().lower()
    if normalized in ('true', 'yes', '1'):
        return True
    if normalized in ('false', 'no', '0'):
        return False
    raise DictionaryBuildError(
        f"header '{key}' must be true or false, got {value!r}", file=file_path)


def resolve_file_type(headers: dict, default_type, file_path) -> str:
    file_type = headers.get('type')
    file_type = file_type.strip() if file_type else None

    effective_type = file_type or default_type
    if not effective_type:
        raise DictionaryBuildError(
            "no 'type' in the file header, and the book's meta.yaml has no default 'type'",
            file=file_path, line=1)

    if effective_type not in utils.KNOWN_TYPES:
        raise DictionaryBuildError(
            f"unknown type '{effective_type}' (expected one of {sorted(utils.KNOWN_TYPES)})",
            file=file_path, line=1)

    return effective_type


def build_book(dict_dir: Path, output_format: str, enable_stats: bool,
                count_frequency: int, stats_file: str, debug: bool = False,
                only_file: str = None, meta_defaults: dict = None):
    """Reads meta.yaml + all input files for one dictionary/book directory
    and returns the generated tabfile/babylon text."""

    meta = utils.load_book_meta(dict_dir, meta_defaults)
    global_exclusions = utils.load_global_exclusions()
    book_exclusions = set(global_exclusions) | set(meta['skip'])

    ALLOWED_METADATA = {'title', 'shlokakey', 'lang', 'skip', 'type', 'auto_shloka'}

    input_files = utils.discover_input_files(dict_dir, meta['folders'])

    if only_file:
        target = Path(only_file)
        if not target.is_absolute():
            target = dict_dir / target
        target = target.resolve()
        matches = [f for f in input_files if f.resolve() == target]
        if not matches:
            print(f"Target: {target}")
            raise DictionaryBuildError(
                f"--file {only_file!r} does not resolve to one of this book's "
                f"input files (checked {len(input_files)} files under {dict_dir} "
                f"and its meta.yaml 'folders')")
        input_files = matches

    if not input_files:
        raise DictionaryBuildError(
            "no .txt files found (check meta.yaml 'folders' if content lives in subdirectories)",
            file=dict_dir)

    processed_output = {}
    stats = None
    if enable_stats:
        stats = StatsBuilder(track_frequency=count_frequency > 0)

    for file_path in input_files:
        with open(file_path, 'r', encoding='utf-8') as f:
            file_content = f.read().strip().rstrip().replace('\r', '')

        # Header/comment lines are parsed off the *raw* content first -
        # bold markup is only meaningful in the records that follow, not
        # in headers or comment lines (which may contain an incidental
        # literal "**", e.g. a "# --*-- coding: utf-8 --**--" line).
        try:
            headers, raw_records_text, n_header_lines = utils.read_header(
                file_content, allowed_tags=ALLOWED_METADATA)
        except DictionaryBuildError as e:
            raise e.with_location(file=file_path)

        records_text = markup.apply_bold_markup(
            raw_records_text, filename=file_path, line_offset=n_header_lines)

        if 'skip' in headers:
            headers['skip'] = [w.strip() for w in headers['skip'].split(';') if w.strip()]

        if 'auto_shloka' in headers:
            headers['auto_shloka'] = parse_bool_header(
                headers['auto_shloka'], 'auto_shloka', file_path)

        file_type = resolve_file_type(headers, meta['type'], file_path)

        # Per-file exclusion set = global + book + this file's own HEADER:skip
        # (HEADER:skip is layered on top inside process_stream itself).
        handler = input_handlers.HandlerFactory.getInputHandler(
            file_type, exclusion_list=book_exclusions, info=str(file_path))

        relative_path = str(file_path.relative_to(dict_dir))
        processed_output[relative_path] = handler.process_stream(
            records_text, headers=headers, line_offset=n_header_lines)

    out_formatter = output_processing.TabfileFormatter(stats)
    if output_format == "babylon":
        out_formatter = output_processing.BabylonFormatter(stats)
    out_data = out_formatter.generate_dictionary(processed_output)

    if stats:
        if count_frequency:
            print(stats.dump_all_files_formatted(
                prefix="Stats:  ",
                supply_top_entries=count_frequency))
        write_stats_to_file(stats, stats_file)

    return out_data, meta


def main():
    args = utils.parse_arguments()

    try:
        out_data, meta = build_book(
            args.dict_dir, args.output_format, args.enable_stats,
            args.count_frequency, stats_file=args.stats_file, debug=args.debug,
            only_file=args.file, meta_defaults=args.meta_defaults)
    except DictionaryBuildError as e:
        print(f"\u274c {e}", file=sys.stderr)
        if args.debug:
            traceback.print_exc()
        print("Output file not written.", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"\u274c Unexpected error (not a source-data problem - likely a bug): {e}",
              file=sys.stderr)
        traceback.print_exc()
        print("Output file not written.", file=sys.stderr)
        sys.exit(2)

    if out_data:
        with open(args.output, 'w', encoding='utf-8') as outfile:
            if args.output_format == "babylon":
                outfile.write(f"\n#bookname={meta['name']}\n#stripmethod=keep\n"
                              f"#sametypesequence=h\n#description={args.version}\n\n{out_data}")
            if args.output_format == "tabfile":
                outfile.write(out_data)

        # Sidecar with the resolved book name, so the build script can pick
        # it up without re-parsing meta.yaml itself.
        name_file = Path(args.output).with_suffix('.name')
        name_file.write_text(meta['name'], encoding='utf-8')

        print(f"\u2705 {meta['name']} [{args.dict_dir}]: {args.output}, {args.stats_file}")
    else:
        print(f"\u26a0\ufe0f  {meta['name']} [{args.dict_dir}]: no entries produced", file=sys.stderr)


if __name__ == "__main__":
    main()
