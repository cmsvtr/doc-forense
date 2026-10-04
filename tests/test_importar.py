import pytest

from forense.importar import importar_pasta, validar_origem


def test_importa_com_subpastas_sem_sobrescrever(caso, tmp_path):
    origem = tmp_path / "SEI_08700.000001_2024-00"
    (origem / "[104]-1157123_Anexo").mkdir(parents=True)
    (origem / "[104]-1157123_Anexo" / "Doc. 1.PDF").write_bytes(b"%PDF anexo 1")
    (origem / "[588]-1215707_E_mail.html").write_text("<p>email</p>", encoding="utf-8")
    (origem / "~$temp.docx").write_bytes(b"lixo")

    r = importar_pasta(caso, origem, log=lambda m: None)
    destino = caso.originais / "SEI_08700.000001_2024-00"
    assert (destino / "[104]-1157123_Anexo" / "Doc. 1.PDF").read_bytes() == b"%PDF anexo 1"
    assert not (destino / "~$temp.docx").exists()
    assert r["copiados"] == 2 and r["total"] == 2

    assert importar_pasta(caso, origem, log=lambda m: None)["ja_existentes"] == 2   # idênticos: pulados
    (origem / "[588]-1215707_E_mail.html").write_text("<p>mudou</p>", encoding="utf-8")
    r = importar_pasta(caso, origem, log=lambda m: None)
    assert r["renomeados"] == 1 and (destino / "[588]-1215707_E_mail (2).html").exists()
    assert (destino / "[588]-1215707_E_mail.html").read_text(encoding="utf-8") == "<p>email</p>"  # não sobrescreve
    assert (origem / "[104]-1157123_Anexo" / "Doc. 1.PDF").exists()                             # origem intacta


def test_recusa_origem_que_contem_o_caso_ou_inexistente(caso, tmp_path):
    with pytest.raises(ValueError):
        validar_origem(caso, caso.raiz.parent)
    with pytest.raises(ValueError):
        validar_origem(caso, caso.originais)
    with pytest.raises(FileNotFoundError):
        validar_origem(caso, tmp_path / "nao_existe")
