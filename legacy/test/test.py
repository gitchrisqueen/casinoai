from pathlib import Path



data_folder = '/Users/christopherqueen/workspace/casinoai/pdfs'
for path in Path(data_folder).rglob('*.pdf'):
    print(f"Processing {path.relative_to(data_folder)} ...")
    #print(f"Processing {path.name} ...")

