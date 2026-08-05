import sys
from pathlib import Path


def main():
    if len(sys.argv) != 3:
        print("Usage: python example_mt3.py <input_audio> <output_musicxml>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(
        f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0">
  <!-- Example MT3 command output -->
  <!-- Input file: {input_path.name} -->
  <part-list>
    <score-part id="P1">
      <part-name>Example MT3 Output</part-name>
    </score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time>
          <beats>4</beats>
          <beat-type>4</beat-type>
        </time>
        <clef>
          <sign>G</sign>
          <line>2</line>
        </clef>
      </attributes>
      <note>
        <rest/>
        <duration>4</duration>
        <type>whole</type>
      </note>
    </measure>
  </part>
</score-partwise>
''',
        encoding="utf-8",
    )

    print(f"Wrote example MusicXML to {output_path}")


if __name__ == "__main__":
    main()
