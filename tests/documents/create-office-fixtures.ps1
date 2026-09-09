$ErrorActionPreference = 'Stop'
$fixtureRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../fixtures/documents'))
New-Item -ItemType Directory -Force -Path $fixtureRoot | Out-Null
& ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../build-resources/python/python.exe'))) (Join-Path $PSScriptRoot 'create-docx-fixture.py')
$ppt = New-Object -ComObject PowerPoint.Application
try {
  $deck = $ppt.Presentations.Add(0)
  $deck.PageSetup.SlideWidth = 960
  $deck.PageSetup.SlideHeight = 540
  foreach($number in 1..2) {
    $slide = $deck.Slides.Add($number,12)
    $title = $slide.Shapes.AddTextbox(1,45,30,860,65)
    $title.TextFrame.TextRange.Text = "문서 윤문 검증 $number"
    $title.TextFrame.TextRange.Font.Name = '맑은 고딕'
    $title.TextFrame.TextRange.Font.Size = 30
    $body = $slide.Shapes.AddTextbox(1,45,130,860,140)
    $body.TextFrame.TextRange.Text = '이 조직은 강한 경쟁력을 가지고 있다. 팀은 풍부한 경험을 가지고 있다.'
    $body.TextFrame.TextRange.Font.Name = '맑은 고딕'
    $body.TextFrame.TextRange.Font.Size = 22
    $body.TextFrame.TextRange.Characters(1,5).Font.Bold = -1
    $table = $slide.Shapes.AddTable(2,2,45,310,860,120).Table
    $table.Cell(1,1).Shape.TextFrame.TextRange.Text = '지역'
    $table.Cell(1,2).Shape.TextFrame.TextRange.Text = '인원'
    $table.Cell(2,1).Shape.TextFrame.TextRange.Text = '서울'
    $table.Cell(2,2).Shape.TextFrame.TextRange.Text = '10명'
    $slide.NotesPage.Shapes.Placeholders.Item(2).TextFrame.TextRange.Text = '발표자 노트 원본 보존'
  }
  $deck.SaveAs((Join-Path $fixtureRoot 'mixed.pptx'),24)
  $deck.Close()
} finally {$ppt.Quit();[void][Runtime.InteropServices.Marshal]::ReleaseComObject($ppt)}
Write-Output 'Office fixtures created.'
