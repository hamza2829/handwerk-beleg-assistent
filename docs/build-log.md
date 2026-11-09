# Build-Log

## 1. Der Belegkopf war ein guter Start

Ich habe mit vier festen Überschriften angefangen: Rechnung, Lieferschein, Angebot und Mahnung. Für solche Belege ist eine Regel nachvollziehbar. Ein Modell für jedes PDF hätte den Ablauf schwerer zu erklären gemacht. Die Regel kann aber danebenliegen, wenn oben der Bezug zu einem anderen Beleg steht. Genau solche Fälle gehören jetzt in den Test.

## 2. Excel ist der Eingang

Ich wollte die Tabelle zuerst mit der App hin und her synchronisieren. Dann wäre bei zwei Änderungen unklar gewesen, welcher Status gilt. Jetzt gibt es einen Import mit Zeilennummern für Fehler. Beim erneuten Import werden Name und Betrag aktualisiert. Der in der App gepflegte Status bleibt erhalten.

## 3. Prüfen statt still korrigieren

Bei wenig Text oder widersprüchlichen Hinweisen landet ein PDF in der Warteschlange. Eine Person kann den Typ bestätigen oder ändern. Ich habe darauf verzichtet, den ursprünglichen Vorschlag zu überschreiben. So bleibt im Datensatz sichtbar, was der Assistent vorgeschlagen hat.

## 4. Testdaten mit Absicht schwierig machen

Eine Sammlung sauber beschrifteter PDFs wäre schnell fertig gewesen. Sie hätte aber wenig über Fehler gezeigt. Deshalb erzeugt der Generator auch PDFs mit ungewohnten Begriffen, gemischten Hinweisen und irreführenden Überschriften. Die Auswertung zählt die Fälle aus der Prüfwarteschlange mit und führt jede falsche Zuordnung auf.

## 5. Die Demo zeigt die laufende App

Für die Startseite hätte ich zwei Ansichten nachbauen können. Stattdessen startet die CI die App mit Beispieldaten. Playwright verknüpft einen Beleg, öffnet die Warteschlange und die Auftragsliste und nimmt beide Ansichten auf. Die Bilder liegen zusammen mit der statischen Seite im Download.
