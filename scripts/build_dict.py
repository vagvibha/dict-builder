import sys
import os
import warnings

# Silence deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Dynamically resolve dictzip on macOS Homebrew without breaking Ubuntu Linux PATH
if os.path.exists("/opt/homebrew/bin"):
    os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ.get("PATH", "")

from pyglossary import Glossary

def build_stardict(input_tsv, output_dir, book_title, build_description):
    os.makedirs(output_dir, exist_ok=True)
    
    Glossary.init()
    glos = Glossary()

    # Read Tabfile/TSV format
    glos.read(input_tsv, format="Tabfile")

    # Set dynamic metadata
    glos.setInfo("title", book_title)
    glos.setInfo("description", build_description)

    # Construct output target .ifo path
    ifo_path = os.path.join(output_dir, f"{book_title.lower()}.ifo")

    # Write directly to Stardict format using direct kwargs
    glos.write(
        ifo_path,
        format="Stardict",
        sametypesequence="h",
        dictzip=True
    )
    print(f"Successfully compiled '{book_title}' into {output_dir}/")

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python3 build_dict.py <input_tsv> <output_dir> <book_title> <build_description>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_directory = sys.argv[2]
    title = sys.argv[3]
    description = sys.argv[4]

    build_stardict(input_file, output_directory, title, description)
