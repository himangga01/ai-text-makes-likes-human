"""Small deterministic WordprocessingML fixture for preservation tests."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from xml.sax.saxutils import escape

root=Path(__file__).resolve().parents[1]/'fixtures/documents'
root.mkdir(parents=True,exist_ok=True)
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
def para(text):return '<w:p><w:r><w:t>'+escape(text)+'</w:t></w:r></w:p>'
parts={
'[Content_Types].xml':'''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/><Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/></Types>''',
'_rels/.rels':f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{R}/officeDocument" Target="word/document.xml"/></Relationships>',
'word/_rels/document.xml.rels':f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{R}/styles" Target="styles.xml"/><Relationship Id="rId2" Type="{R}/header" Target="header1.xml"/><Relationship Id="rId3" Type="{R}/footer" Target="footer1.xml"/></Relationships>',
'word/styles.xml':f'<w:styles xmlns:w="{W}"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Malgun Gothic" w:eastAsia="맑은 고딕"/><w:sz w:val="24"/></w:rPr></w:rPrDefault></w:docDefaults><w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="40"/></w:rPr></w:style></w:styles>',
'word/header1.xml':f'<w:hdr xmlns:w="{W}">'+para('머리글 원본 보존')+'</w:hdr>',
'word/footer1.xml':f'<w:ftr xmlns:w="{W}">'+para('바닥글 원본 보존')+'</w:ftr>',
}
body='<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>문서 윤문 검증</w:t></w:r></w:p>'
body+='<w:p><w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">이 문서는 </w:t></w:r><w:r><w:t>강한 경쟁력을 가지고 있다. 내용을 자연스럽게 다듬는다.</w:t></w:r></w:p>'
body+=para('서울 지사는 10명이고 부산 지사는 20명이다.')+para('그는 “승인한다”고 말했다.')
body+='<w:tbl><w:tblPr><w:tblW w:w="9000" w:type="dxa"/><w:tblBorders>'+''.join(f'<w:{x} w:val="single" w:sz="4" w:color="D9D9D9"/>' for x in ['top','left','bottom','right','insideH','insideV'])+'</w:tblBorders></w:tblPr><w:tblGrid><w:gridCol w:w="2500"/><w:gridCol w:w="6500"/></w:tblGrid>'
for cells in [('항목','설명'),('운영','안정적인 운영 역량을 가지고 있다.')]:
    body+='<w:tr>'+''.join('<w:tc><w:tcPr/>'+para(t)+'</w:tc>' for t in cells)+'</w:tr>'
body+='</w:tbl>'
body+='<w:p><w:r><w:pict><v:shape id="TextBox1" style="width:350pt;height:50pt" stroked="f"><v:textbox><w:txbxContent>'+para('팀은 풍부한 경험을 가지고 있다.')+'</w:txbxContent></v:textbox></v:shape></w:pict></w:r></w:p>'
body+='<w:sectPr><w:headerReference w:type="default" r:id="rId2"/><w:footerReference w:type="default" r:id="rId3"/><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
parts['word/document.xml']=f'<w:document xmlns:w="{W}" xmlns:r="{R}" xmlns:v="urn:schemas-microsoft-com:vml"><w:body>'+body+'</w:body></w:document>'
with ZipFile(root/'mixed.docx','w',ZIP_DEFLATED) as z:
    for name,value in parts.items():z.writestr(name,('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'+value).encode('utf-8'))
print(root/'mixed.docx')
