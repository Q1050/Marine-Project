from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


TEST_DIR = Path(
    "data/pterois_dataset/split/test"
)

OUTPUT_FILE = Path(
    "pterois_test_contact_sheet.jpg"
)

THUMB_WIDTH = 250
THUMB_HEIGHT = 200

COLUMNS = 5

LABEL_HEIGHT = 55


images = []


for species_dir in sorted(
    TEST_DIR.iterdir()
):

    if not species_dir.is_dir():
        continue

    for path in sorted(
        species_dir.iterdir()
    ):

        if path.suffix.lower() not in {
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
        }:
            continue

        images.append(
            (
                species_dir.name,
                path
            )
        )


rows = (
    len(images)
    + COLUMNS
    - 1
) // COLUMNS


sheet_width = (
    COLUMNS
    * THUMB_WIDTH
)

sheet_height = (
    rows
    * (
        THUMB_HEIGHT
        + LABEL_HEIGHT
    )
)


sheet = Image.new(
    "RGB",
    (
        sheet_width,
        sheet_height
    ),
    "white"
)


draw = ImageDraw.Draw(
    sheet
)


for index, (
    species,
    path
) in enumerate(images):

    row = (
        index
        // COLUMNS
    )

    column = (
        index
        % COLUMNS
    )


    x = (
        column
        * THUMB_WIDTH
    )

    y = (
        row
        * (
            THUMB_HEIGHT
            + LABEL_HEIGHT
        )
    )


    image = Image.open(
        path
    ).convert("RGB")


    image.thumbnail(
        (
            THUMB_WIDTH,
            THUMB_HEIGHT
        )
    )


    offset_x = (
        x
        + (
            THUMB_WIDTH
            - image.width
        ) // 2
    )

    offset_y = (
        y
        + (
            THUMB_HEIGHT
            - image.height
        ) // 2
    )


    sheet.paste(
        image,
        (
            offset_x,
            offset_y
        )
    )


    label = (
        f"{species}\n"
        f"{path.name}"
    )


    draw.text(
        (
            x + 5,
            y + THUMB_HEIGHT + 5
        ),
        label,
        fill="black"
    )


sheet.save(
    OUTPUT_FILE,
    quality=95
)


print(
    f"Contact sheet saved to:"
    f"\n{OUTPUT_FILE}"
)