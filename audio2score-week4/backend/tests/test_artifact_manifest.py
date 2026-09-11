from engine.artifacts import ArtifactKind, ArtifactManifest, ArtifactRef, ref_for_file


def test_manifest_roundtrip(tmp_path):
    path = tmp_path / "raw.mid"
    path.write_bytes(b"MThd")
    manifest = ArtifactManifest(job_id="j1")
    manifest.add(ref_for_file(ArtifactKind.RAW_MIDI, path, content_type="audio/midi"))
    dest = manifest.write_json(tmp_path / "manifest.json")
    loaded = ArtifactManifest.read_json(dest)
    assert loaded.job_id == "j1"
    assert loaded.find(ArtifactKind.RAW_MIDI)[0].sha256 == manifest.artifacts[0].sha256
    assert loaded.artifacts[0].bytes == 4
