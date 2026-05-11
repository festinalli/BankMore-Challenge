import { Pipe, PipeTransform } from '@angular/core';

@Pipe({
  name: 'dateBr',
  standalone: true
})
export class DateBrPipe implements PipeTransform {
  transform(value: string | null | undefined): string {
    if (!value) {
      return '';
    }

    try {
      const date = new Date(value);
      return new Intl.DateTimeFormat('pt-BR', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
      }).format(date);
    } catch (error) {
      return value;
    }
  }
}
