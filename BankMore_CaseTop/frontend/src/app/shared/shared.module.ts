import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ButtonComponent } from './components/button/button.component';
import { InputComponent } from './components/input/input.component';
import { CurrencyBrlPipe } from './pipes/currency-brl.pipe';
import { DateBrPipe } from './pipes/date-br.pipe';

@NgModule({
  declarations: [],
  imports: [
    CommonModule,
    FormsModule,
    ButtonComponent,
    InputComponent,
    CurrencyBrlPipe,
    DateBrPipe
  ],
  exports: [
    ButtonComponent,
    InputComponent,
    CurrencyBrlPipe,
    DateBrPipe
  ]
})
export class SharedModule { }
