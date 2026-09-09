$ErrorActionPreference='Stop'
$repoRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$qaRoot=[IO.Path]::GetFullPath((Join-Path $repoRoot 'runtime/test-tmp/document-qa'))
New-Item -ItemType Directory -Force -Path $qaRoot | Out-Null
$records=[Collections.Generic.List[object]]::new()
$word=New-Object -ComObject Word.Application
Write-Output 'Word connected'
$word.Visible=$false
$word.DisplayAlerts=0
try {
  foreach($name in @('original','codex','claude')) {
    $file=if($name -eq 'original'){Join-Path $repoRoot 'tests/fixtures/documents/mixed.docx'}else{Join-Path $repoRoot "runtime/test-tmp/document-live/$name-humanized.docx"}
    $file=[IO.Path]::GetFullPath($file)
    Write-Output "Opening DOCX $name"
    $doc=$word.Documents.Open($file,$false,$true,$false)
    Write-Output "Opened DOCX $name"
    [string]$pdfPath=[IO.Path]::GetFullPath((Join-Path $qaRoot "$name-docx.pdf"))
    $doc.ExportAsFixedFormat($pdfPath,17)
    Write-Output "Rendered DOCX $name"
    $pages=$doc.ComputeStatistics(2)
    $records.Add(@{format='docx';name=$name;pages=$pages;opened=$true})
    $doc.Close(0)
  }
} finally {$word.Quit();[void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)}
$ppt=New-Object -ComObject PowerPoint.Application
try {
  foreach($name in @('original','codex','claude')) {
    $file=if($name -eq 'original'){Join-Path $repoRoot 'tests/fixtures/documents/mixed.pptx'}else{Join-Path $repoRoot "runtime/test-tmp/document-live/$name-humanized.pptx"}
    $file=[IO.Path]::GetFullPath($file)
    $deck=$ppt.Presentations.Open($file,-1,0,0)
    $overflow=@()
    foreach($slide in $deck.Slides) {
      $slide.Export((Join-Path $qaRoot "$name-pptx-$($slide.SlideIndex).png"),'PNG',1600,900)
      foreach($shape in $slide.Shapes) {
        if($shape.HasTextFrame -and $shape.TextFrame.HasText) {
          $available=$shape.Height-$shape.TextFrame.MarginTop-$shape.TextFrame.MarginBottom
          if($shape.TextFrame.TextRange.BoundHeight -gt $available+1){$overflow+=@{slide=$slide.SlideIndex;shape=$shape.Id}}
        }
      }
    }
    $records.Add(@{format='pptx';name=$name;slides=$deck.Slides.Count;opened=$true;overflow=$overflow})
    $deck.Close()
  }
} finally {$ppt.Quit();[void][Runtime.InteropServices.Marshal]::ReleaseComObject($ppt)}
$records | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $qaRoot 'office-validation.json') -Encoding UTF8
$records | ConvertTo-Json -Depth 5
